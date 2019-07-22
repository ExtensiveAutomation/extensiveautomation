#!/usr/bin/env python
# -*- coding: utf-8 -*-

# -------------------------------------------------------------------
# Copyright (c) 2010-2019 Denis Machard
# This file is part of the extensive automation project
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA
# -------------------------------------------------------------------

import os
import sys
import subprocess
import shutil
import zlib
import base64
import tarfile
try:
    import scandir
except ImportError:  # for python3 support
    scandir=os
import copy
import json
import re

# unicode = str with python3
if sys.version_info > (3,):
    unicode = str

try:
    xrange
except NameError: # support python3
    xrange = range
    
from Libs import Settings, Logger

try:
    import RepoManager
except ImportError:
    from . import RepoManager
    
import Libs.FileModels.TestPlan as TestPlan
import Libs.FileModels.TestUnit as TestUnit
import Libs.FileModels.TestSuite as TestSuite

from ServerInterfaces import EventServerInterface as ESI
from ServerEngine import ( Common, DbManager, ProjectsManager )

REPO_TYPE = 0


def uniqid():
    """
    Return a unique id
    """
    from time import time
    return hex(int(time()*10000000))[2:]

    
TS_ENABLED				= "2"
TS_DISABLED				= "0"


class RepoTests(RepoManager.RepoManager, Logger.ClassLogger):
    """
    Tests repository class
    """
    def __init__(self, context):
        """
        Repository manager for tests files
        """
        RepoManager.RepoManager.__init__(self,
                                        pathRepo='%s%s' % ( Settings.getDirExec(), 
                                                            Settings.get( 'Paths', 'tests' ) ),
                                        extensionsSupported = [ RepoManager.TEST_SUITE_EXT, 
                                                                RepoManager.TEST_PLAN_EXT, 
                                                                RepoManager.TEST_CONFIG_EXT, 
                                                                RepoManager.TEST_DATA_EXT,
                                                                RepoManager.TEST_UNIT_EXT, 
                                                                RepoManager.PNG_EXT, 
                                                                RepoManager.TEST_GLOBAL_EXT ],
                                       context=context)
                                       
        self.context=context
        self.tb_variables = 'test-environment'

        # load variables in cache, new in v19
        self.__cache_vars = []
        self.loadCacheVars()

    def loadCacheVars(self):
        """
        load all projects in cache
        """
        self.trace("Updating variables memory cache from database")
        
        code, vars_list = self.getVariablesFromDB()
        if code == self.context.CODE_ERROR:
            raise Exception("Unable to get variables from database")

        self.__cache_vars = vars_list
        self.trace("Variables cache Size=%s" % len(self.__cache_vars) )
        
    def cacheVars(self):
        """
        Return accessor for the cache
        """
        return self.__cache_vars
        
    def trace(self, txt):
        """
        Trace message
        """
        Logger.ClassLogger.trace(self, txt="RPT - %s" % txt)

    def getTree(self, b64=False, project=1):
        """
        Returns tree
        """
        return self.getListingFilesV2(path="%s/%s" % (self.testsPath, str(project)), 
                                      project=project, supportSnapshot=True  )

    def __getBasicListing(self, testPath, initialPath):
        """
        """
        listing = []
        for entry in list(scandir.scandir( testPath ) ):
            if not entry.is_dir(follow_symlinks=False):
                filePath = entry.path
                listing.append( filePath.split(initialPath)[1] )
            else:
                listing.extend( self.__getBasicListing(testPath=entry.path, initialPath=initialPath) )
        return listing
        
    def getBasicListing(self, projectId=1):
        """
        """
        listing = []
        initialPath = "%s/%s" % (self.testsPath, projectId)
        for entry in list(scandir.scandir( initialPath ) ) :
            if not entry.is_dir(follow_symlinks=False):
                filePath = entry.path
                listing.append( filePath.split(initialPath)[1] )
            else:
                listing.extend( self.__getBasicListing(testPath=entry.path, initialPath=initialPath) )
        return listing

    def addtf2tg(self, data_):
        """
        Add remote testplan, testsuites or testunit in the testglobal
        internal function

        @param data_:
        @type data_:
        """
        ret = ( self.context.CODE_OK, "")
        alltests = []
        # read each test files in data
        for ts in data_:
            # backward compatibility
            if 'alias' not in ts:
                ts['alias'] = ''
                
            # extract project info
            prjName = str(ts['file']).split(":", 1)[0]
            ts.update( { 'testproject': prjName } )
            
            # extract test name
            tmp = str(ts['file']).split(":", 1)[1].rsplit("/", 1)
            if len(tmp) > 1:
                filenameTs, fileExt = tmp[1].rsplit(".", 1)
            else:
                filenameTs, fileExt = tmp[0].rsplit(".", 1)
                
            # extract test path
            tmp = str(ts['file']).split(":", 1)[1].rsplit("/", 1)
            if len(tmp) > 1:
                testPath = "/%s" % tmp[0]
            else:
                testPath = "/"
            ts.update( { 'testpath': testPath } )
            
            if ts['type'] == "remote" and ts['enable'] == TS_DISABLED:
                ts.update( { 'path': filenameTs, 'depth': 1 } )
                alltests.append( ts )
                
            if ts['type'] == "remote" and ts['enable'] == TS_ENABLED:
                # extract the project name then the project id
                prjID = 0
                absPath = ''
                try:
                    prjName, absPath = ts['file'].split(':', 1)
                except Exception as e:
                    self.error("unable to extract project name: %s" % str(e) )
                    ret = ( self.context.CODE_NOT_FOUND, "ID=%s %s" % (ts['id'],ts['file'])  )
                    break   
                else:
                    prjID = ProjectsManager.instance().getProjectID(name=prjName)

                    # prepare data model according to the test extension
                    if absPath.endswith(RepoManager.TEST_SUITE_EXT):
                        doc = TestSuite.DataModel()
                    elif absPath.endswith(RepoManager.TEST_UNIT_EXT):
                        doc = TestUnit.DataModel()
                    elif absPath.endswith(RepoManager.TEST_PLAN_EXT):
                        doc = TestPlan.DataModel()
                    else:
                        self.error("unknown test extension file: %s" % absPath )
                        ret = ( self.context.CODE_NOT_FOUND, "ID=%s %s" % (ts['id'],ts['file'])  )
                        break
                    
                    # load the data model
                    res = doc.load( absPath = "%s/%s/%s" % ( self.testsPath, prjID, absPath ) )
                    if not res:
                        ret = ( self.context.CODE_NOT_FOUND, absPath  )
                        break   
                    else:
                        # update/add test parameters with the main parameters of the test global
                        self.__updatetsparams( currentParam=doc.properties['properties']['inputs-parameters']['parameter'],
                                                newParam=ts['properties']['inputs-parameters']['parameter'] )
                        # fix in v11, properly dispatch agent keys                        
                        self.__updatetsparams( currentParam=doc.properties['properties']['agents']['agent'],
                                                newParam=ts['properties']['agents']['agent'] )
                        # end of fix
                        ts['properties']['inputs-parameters'] = doc.properties['properties']['inputs-parameters']
                        # fix in v11, properly dispatch agent keys
                        ts['properties']['agents'] = doc.properties['properties']['agents']
                        # end of fix
                        
                        if fileExt == RepoManager.TEST_SUITE_EXT:
                            ts.update( { 'test-definition': doc.testdef, 
                                         'test-execution': doc.testexec,
                                         'path': filenameTs } )
                            alltests.append( ts )
                        elif fileExt == RepoManager.TEST_UNIT_EXT:
                            ts.update( { 'test-definition': doc.testdef, 
                                         'path': filenameTs } )
                            alltests.append( ts )
                        elif fileExt == RepoManager.TEST_PLAN_EXT:
                            self.trace('Reading sub test plan')
                            sortedTests = doc.getSorted()
                            subret, suberr = self.addtf2tp( data_=sortedTests, tpid=ts['id'] )
                            ret = (subret, suberr)
                            if subret != self.context.CODE_OK:
                                del sortedTests
                                break
                            else:
                                alias_ts = ts['alias']
                                # fix issue encode, ugly fix
                                try:
                                    alias_ts =  str(alias_ts)
                                except UnicodeEncodeError as e:
                                    pass
                                else:
                                    try:
                                        alias_ts = alias_ts.encode('utf8')
                                    except UnicodeDecodeError as e:
                                        alias_ts = alias_ts.decode('utf8')
                                # end of fix
                        
                                # add testplan separator
                                alltests.extend( [{'extension': 'tpx', 
                                                   'separator': 'started', 
                                                   'enable': "0" , 
                                                   'depth': 1, 
                                                   'id': ts['id'], 
                                                   'testname': filenameTs,
                                                   'parent': ts['parent'], 
                                                   'alias': alias_ts,
                                                   'properties': ts['properties'],
                                                   "testpath": ts['testpath'], 
                                                   "testproject": ts['testproject'] }] ) 
                                                    
                                # update all subtest with parameters from testplan
                                for i in xrange(len(sortedTests)):
                                    self.__updatetsparams( currentParam=sortedTests[i]['properties']['inputs-parameters']['parameter'],
                                                         newParam=ts['properties']['inputs-parameters']['parameter'] )
                                    self.__updatetsparams( currentParam=sortedTests[i]['properties']['outputs-parameters']['parameter'],
                                                         newParam=ts['properties']['outputs-parameters']['parameter'] )
                                    # fix in v11, properly dispatch agent keys    
                                    self.__updatetsparams( currentParam=sortedTests[i]['properties']['agents']['agent'],
                                                         newParam=ts['properties']['agents']['agent'] )
                                    # end of fix
                                self.trace('Read sub test plan finished')
                                
                                alltests.extend( sortedTests )
                                alltests.extend( [{ 
                                                    'extension': 'tpx', 
                                                    'separator': 'terminated',  
                                                    'enable': "0" , 
                                                    'depth': 1, 
                                                    'id': ts['id'], 
                                                    'testname': filenameTs, 
                                                    'parent': ts['parent'], 
                                                    'alias': alias_ts }] )
        return ret + (alltests, )

    def addtf2tp(self, data_, tpid=0):
        """
        Add remote testsuites or testunit in the testplan
        Internal function

        @param data_:
        @type data_:
        """
        ret = (self.context.CODE_OK, "")
        for ts in data_:
            # extract project info
            prjName = str(ts['file']).split(":", 1)[0]
            ts.update( { 'testproject': prjName } )
            
            # extract test name
            tmp = str(ts['file']).split(":", 1)[1].rsplit("/", 1)
            if len(tmp) > 1:
                filenameTs, fileExt = tmp[1].rsplit(".", 1)
            else:
                filenameTs, fileExt = tmp[0].rsplit(".", 1)
           
            # extract test path
            tmp = str(ts['file']).split(":", 1)[1].rsplit("/", 1)
            if len(tmp) > 1:
                testPath = "/%s" % tmp[0]
            else:
                testPath = "/"
            ts.update( { 'testpath': testPath } )
            
            if ts['type'] == "remote" and ts['enable'] == TS_DISABLED:
                ts.update( { 'path': filenameTs, 'tpid': tpid } )
                # backward compatibility
                self.__fixAliasTp(ts=ts)
                        
            elif ts['type'] == "remote" and ts['enable'] == TS_ENABLED:
                prjID = 0
                absPath = ''
                try:
                    prjName, absPath = ts['file'].split(':', 1)
                except Exception as e:
                    self.error("unable to extract project name: %s" % str(e) )
                    ret = ( self.context.CODE_NOT_FOUND, "ID=%s %s" % (ts['id'],ts['file'])  )
                    break   
                else:
                    prjID = ProjectsManager.instance().getProjectID(name=prjName)
                    if absPath.endswith(RepoManager.TEST_SUITE_EXT):
                        doc = TestSuite.DataModel()
                    else:
                        doc = TestUnit.DataModel()
                    res = doc.load( absPath = "%s/%s/%s" % ( self.testsPath, prjID, absPath ) )
                    if not res:
                        ret = ( self.context.CODE_NOT_FOUND, "ID=%s %s" % (ts['id'],ts['file'])  )
                        break   
                    else:

                        #
                        self.__updatetsparams( currentParam=doc.properties['properties']['inputs-parameters']['parameter'],
                                                newParam=ts['properties']['inputs-parameters']['parameter'] )
                        self.__updatetsparams( currentParam=doc.properties['properties']['outputs-parameters']['parameter'],
                                                newParam=ts['properties']['outputs-parameters']['parameter'] )
                        
                        # fix in v11, properly dispatch agent keys                        
                        self.__updatetsparams( currentParam=doc.properties['properties']['agents']['agent'],
                                                newParam=ts['properties']['agents']['agent'] )
                        # end of fix
                        
                        ts['properties']['inputs-parameters'] = doc.properties['properties']['inputs-parameters']
                        ts['properties']['outputs-parameters'] = doc.properties['properties']['outputs-parameters']
                        
                        # fix in v11, properly dispatch agent keys
                        ts['properties']['agents'] = doc.properties['properties']['agents']
                        # end of fix
                        
                        if fileExt == RepoManager.TEST_SUITE_EXT:
                            ts.update( { 'test-definition': doc.testdef, 
                                         'test-execution': doc.testexec, 
                                         'path': filenameTs, 'tpid': tpid } )
                        else:
                            ts.update( { 'test-definition': doc.testdef, 
                                         'path': filenameTs, 'tpid': tpid } )
                
                        # backward compatibility
                        self.__fixAliasTp(ts=ts)
            else:
                pass
        return ret

    def __fixAliasTp(self, ts):
        """
        """
        # backward compatibility
        if 'alias' not in ts:
            ts['alias'] = ''
        
        # fix issue encode, ugly fix
        try:
            ts['alias'] =  str(ts['alias'])
        except UnicodeEncodeError:
            pass
        else:
            try:
                ts['alias'] = ts['alias'].encode('utf8')
            except UnicodeDecodeError:
                ts['alias'] = ts['alias'].decode('utf8')
    
    def __updatetsparams(self, currentParam, newParam):
        """
        Update current test parameters with main parameter
        Internal function

        @param currentParam:
        @type currentParam:

        @param newParam:
        @type newParam:
        """
        for i in xrange(len(currentParam)):
            for np in newParam:
                if np['name'] == currentParam[i]['name'] and currentParam[i]['type'] != "alias":
                    currentParam[i] = np
        # adding new param
        newparams = self.__getnewparams(currentParam, newParam)
        for np in newparams:
            currentParam.append( np )

    def __getnewparams(self, currentParam, newParam):
        """
        New param to add
        Internal function

        @param currentParam:
        @type currentParam:

        @param newParam:
        @type newParam:
        """
        toAdd  = []
        for np in newParam:
            isNew = True
            for cp in currentParam:
                if np['name'] == cp['name']:
                    isNew = False
            if isNew:
                toAdd.append( np )
        return toAdd

    def findInstance(self, filePath, projectName, projectId):
        """
        Find a test instance according to the path of the file
        """
        self.trace("Find tests instance: %s" % filePath)
        
        if filePath.startswith("/"): filePath = filePath[1:]
        
        tests = []
        try:
            for path, _, files in os.walk("%s/%s" % (self.testsPath, projectId) ):
                for name in files:  
                    if name.endswith(RepoManager.TEST_PLAN_EXT) or name.endswith(RepoManager.TEST_GLOBAL_EXT) :
                        doc = TestPlan.DataModel()
                        res = doc.load( absPath = os.path.join(path, name) )
                        if not res:
                            self.error( 'unable to read test plan: %s' % os.path.join(path, name) )
                        else:
                            testsfile = doc.testplan['testplan']['testfile']
                            t= {"instance": 0}
                            testFound = False
                            for i in xrange(len(testsfile)):
                                if testsfile[i]['type'] == 'remote':
                                    if "%s:%s" % (projectName, filePath) == testsfile[i]['file']:
                                        p = os.path.join(path, name)
                                        p = p.split( "%s/%s" % (self.testsPath, projectId) )[1]
                                        t['test'] = p
                                        t['instance'] += 1
                                        testFound = True
                            if testFound: tests.append(t)
  
        except Exception as e:
            self.error( "unable to find test instance: %s" % e )
            return (self.context.CODE_ERROR, tests)
        return (self.context.CODE_OK, tests)
    
    def getFile(self, pathFile, binaryMode=True, project='', addLock=True, login='', 
                    forceOpen=False, readOnly=False):
        """
        New in v17
        Return the file ask by the tester
        and check the file content for testplan or testglobal
        """
        ret = RepoManager.RepoManager.getFile(self, pathFile=pathFile, 
                                                    binaryMode=binaryMode, 
                                                    project=project, 
                                                    addLock=addLock, 
                                                    login=login, 
                                                    forceOpen=forceOpen, 
                                                    readOnly=readOnly)
        result, path_file, name_file, ext_file, project, _, locked, locked_by = ret
        if result != self.context.CODE_OK:
            return ret
            
        if ext_file in [ RepoManager.TEST_PLAN_EXT, RepoManager.TEST_GLOBAL_EXT]:
            self.trace("get specific file of type %s" % ext_file )
            # checking if all links are good
            doc = TestPlan.DataModel()
            absPath =  "%s/%s/%s" % (self.testsPath, project, pathFile)
            if not doc.load( absPath =  absPath ):
                self.error( 'unable to read test plan: %s/%s/%s' % (self.testsPath, project, pathFile) )
                return ret
            else:
                testsfile = doc.testplan['testplan']['testfile']
                
                # get all projcts
                _, projectsList = ProjectsManager.instance().getProjectsFromDB()
                
                # read all tests file defined in the testplan or testglobal
                for i in xrange(len(testsfile)):
                    # update only remote file
                    if testsfile[i]['type'] == 'remote':
                        # mark as missing ? 
                        prjName, testPath = testsfile[i]['file'].split(":", 1)
                        prjId = 0
                        for prj in projectsList:
                            if prj["name"] == prjName: 
                                prjId = int(prj["id"])
                                break

                        if not os.path.exists(  "%s/%s/%s" % (self.testsPath, prjId, testPath)  ):
                            testsfile[i]["control"] = "missing"
                        else:
                            testsfile[i]["control"] = ""
                            
                # finally save the change
                doc.write( absPath=absPath )
                return (result, path_file, name_file, ext_file, project, doc.getRaw(), locked, locked_by)
            return ret
        else:
            return ret
    
    def delDir(self, pathFolder, project=''):
        """
        Delete a folder
        """
        # folders reserved
        mp = "%s/%s/" % (self.testsPath, project)
        mp_full = os.path.normpath( "%s/%s" % (mp,unicode(pathFolder)) )
        if mp_full == os.path.normpath( "%s/@Recycle" % (mp) ) :
            return self.context.CODE_FORBIDDEN
        if mp_full == os.path.normpath( "%s/@Sandbox" % (mp) ) :
            return self.context.CODE_FORBIDDEN
        # end of new
        
        return RepoManager.RepoManager.delDir(self, 
                                              pathFolder=pathFolder, 
                                              project=project)

    def delDirAll(self, pathFolder, project=''):
        """
        Delete a folder and all inside
        """
        # folders reserved
        mp = "%s/%s/" % (self.testsPath, project)
        mp_full = os.path.normpath( "%s/%s" % (mp,unicode(pathFolder)) ) 
        if mp_full == os.path.normpath( "%s/@Recycle" % (mp) ) :
            return self.context.CODE_FORBIDDEN
        if mp_full == os.path.normpath( "%s/@Sandbox" % (mp) ) :
            return self.context.CODE_FORBIDDEN
        # end of new
         
        return RepoManager.RepoManager.delDirAll(self, 
                                                 pathFolder=pathFolder, 
                                                 project=project)
  
    def moveDir(self, mainPath, folderName, newPath, project='', 
                newProject='', projectsList=[], renamedBy=None):
        """
        Move a folder
        """
        # folders reserved new in v17
        mp = "%s/%s/" % (self.testsPath, project)
        mp_full = os.path.normpath( "%s/%s/%s" % (mp, mainPath, unicode(folderName)) )
        if mp_full == os.path.normpath( "%s/@Recycle" % (mp) ) :
            return (self.context.CODE_FORBIDDEN, mainPath, folderName, newPath, project)
        if mp_full == os.path.normpath( "%s/@Sandbox" % (mp) ) :
            return (self.context.CODE_FORBIDDEN, mainPath, folderName, newPath, project)
        # end of new
        
        # execute the rename function as before
        ret = RepoManager.RepoManager.moveDir(self, 
                                              mainPath=mainPath, 
                                              folderName=folderName, 
                                              newPath=newPath, 
                                              project=project, 
                                              newProject=newProject)
        return ret
        
    def moveFile(self, mainPath, fileName, extFilename, newPath, project='', newProject='', 
                        supportSnapshot=False, projectsList=[], renamedBy=None):
        """
        Move a file
        """
        # execute the rename function as before
        ret = RepoManager.RepoManager.moveFile( self, 
                                                mainPath=mainPath, 
                                                fileName=fileName, 
                                                extFilename=extFilename, 
                                                newPath=newPath, 
                                                project=project, 
                                                newProject=newProject, 
                                                supportSnapshot=supportSnapshot)

        return ret
        
    def duplicateDir(self, mainPath, oldPath, newPath, project='', newProject='', newMainPath=''):
        """
        Duplicate a folder
        """
        # folders reserved new in v17
        mp = "%s/%s/" % (self.testsPath, project)
        mp_full = os.path.normpath( "%s/%s/%s" % (mp, mainPath, unicode(oldPath)) )
        if mp_full == os.path.normpath( "%s/@Recycle" % (mp) ) :
            return (self.context.CODE_FORBIDDEN)
        if mp_full == os.path.normpath( "%s/@Sandbox" % (mp) ) :
            return (self.context.CODE_FORBIDDEN)
        # end of new
        
        return  RepoManager.RepoManager.duplicateDir(self, 
                                                     mainPath=mainPath, 
                                                     oldPath=oldPath, 
                                                     newPath=newPath, 
                                                     project=project, 
                                                     newProject=newProject, 
                                                     newMainPath=newMainPath)
                                                     
    def renameDir(self, mainPath, oldPath, newPath, project='', projectsList=[], renamedBy=None):
        """
        Rename a folder
        """
        # folders reserved new in v17
        mp = "%s/%s/" % (self.testsPath, project)
        mp_full = os.path.normpath( "%s/%s/%s" % (mp, mainPath, unicode(oldPath)) )
        if mp_full == os.path.normpath( "%s/@Recycle" % (mp) ) :
            return (self.context.CODE_FORBIDDEN, mainPath, oldPath, newPath, project)
        if mp_full == os.path.normpath( "%s/@Sandbox" % (mp) ) :
            return (self.context.CODE_FORBIDDEN, mainPath, oldPath, newPath, project)
        # end of new
         
        # execute the rename function as before
        ret = RepoManager.RepoManager.renameDir(self, 
                                                mainPath=mainPath, 
                                                oldPath=oldPath, 
                                                newPath=newPath, 
                                                project=project)

        return ret
        
    def renameFile(self, mainPath, oldFilename, newFilename, extFilename, project='', 
                    supportSnapshot=False, projectsList=[], renamedBy=None):
        """
        Rename a file
        New in v17
        And save the change in the history
        """
        # execute the rename function as before
        ret = RepoManager.RepoManager.renameFile(   self, mainPath=mainPath, 
                                                    oldFilename=oldFilename, 
                                                    newFilename=newFilename,
                                                    extFilename=extFilename, 
                                                    project=project, 
                                                    supportSnapshot=supportSnapshot )

        return ret
        
    # dbr13 >>
    def getTestFileUsage(self, file_path, project_id, user_login):

        project_name = ProjectsManager.instance().getProjectName(prjId=project_id)
        projects = ProjectsManager.instance().getProjects(user=user_login)
        # escape special character
        escaped_file_path = '/'.join([re.escape(path) for path in file_path.rsplit('/')])
        usage_path_file_regex = re.compile('%s:/*%s' % (project_name, escaped_file_path))
        extFile = file_path.rsplit('.')[-1]

        search_result = []

        for proj in projects:
            project_id = proj['project_id']
            tmp_proj_info = {}
            tmp_proj_info.update(proj)
            tmp_proj_info['content'] = []
            tmp_content = tmp_proj_info['content']
            _, _, listing, _ = self.getTree(project=project_id)
            tests_tree_update_locations = self.getTestsForUpdate(listing=listing, extFileName=extFile)
            files_paths = self.get_files_paths(tests_tree=tests_tree_update_locations)

            for file_path in files_paths:

                if file_path.endswith(RepoManager.TEST_PLAN_EXT):
                    doc = TestPlan.DataModel()
                elif file_path.endswith(RepoManager.TEST_GLOBAL_EXT):
                    doc = TestPlan.DataModel(isGlobal=True)
                else:
                    return "Bad file extension: %s" % file_path
                absPath = '%s%s%s' % (self.testsPath, project_id, file_path)
                doc.load(absPath=absPath)
                test_files_list = doc.testplan['testplan']['testfile']
                line_ids = []
                for test_file in test_files_list:
                    if re.findall(usage_path_file_regex, test_file['file']):
                        line_ids.append(test_file['id'])

                tmp_content.append({'file_path': file_path, 'lines_id': line_ids}) if line_ids else None

            search_result.append(tmp_proj_info)
        return search_result

    # dbr13 >>
    def updateLinkedScriptPath(self, project, mainPath, oldFilename, extFilename,
                               newProject, newPath, newFilename, newExt, user_login, 
                               file_referer_path='', file_referer_projectid=0):
        """
        Fix linked test in testplan or testglobal
        Pull request by dbr13 and updated by dmachard
        """
        # get current project name and accessible projects list for currnet user
        project_name = ProjectsManager.instance().getProjectName(prjId=project)        
        new_project_name = new_project_name = ProjectsManager.instance().getProjectName(prjId=newProject)
          
        projects = ProjectsManager.instance().getProjects(user=user_login)
  
        updated_files_list = []

        new_test_file_name = '%s:/%s/%s.%s' % (new_project_name,
                                                newPath,
                                                newFilename, 
                                                newExt)
        old_test_file_name = '%s:/%s/%s.%s' % (project_name,
                                               mainPath,
                                               oldFilename, 
                                               extFilename)
                                                   
        # cleanup the path  of the old and new one                                              
        new_test_file_name = os.path.normpath(new_test_file_name)
        old_test_file_name = os.path.normpath(old_test_file_name)
        
        self.trace("Update link - test path to search: %s" % old_test_file_name)
        self.trace("Update link - replace the old one by the new path: %s" % new_test_file_name)
   
        for proj_id in projects:
            project_id = proj_id['project_id']
            _, _, listing, _ = self.getTree(project=project_id)

            tests_tree_update_locations = self.getTestsForUpdate(listing=listing,
                                                                 extFileName=extFilename)

            if len(file_referer_path) and int(proj_id['project_id']) == int(file_referer_projectid):
                files_paths = self.get_files_paths(tests_tree=tests_tree_update_locations, 
                                                   exceptions=[file_referer_path])
            else:
                files_paths = self.get_files_paths(tests_tree=tests_tree_update_locations)
                
            for file_path in files_paths:
                # init appropriate data model for current file path
                if file_path.endswith(RepoManager.TEST_PLAN_EXT):
                    doc = TestPlan.DataModel()
                    ext_file_name = RepoManager.TEST_PLAN_EXT
                elif file_path.endswith(RepoManager.TEST_GLOBAL_EXT):
                    doc = TestPlan.DataModel(isGlobal=True)
                    ext_file_name =RepoManager.TEST_GLOBAL_EXT
                else:
                    return "Bad file extension: %s" % file_path

                absPath = '%s%s%s' % (self.testsPath, 
                                      project_id, 
                                      file_path)
                doc.load(absPath=absPath)
                test_files_list = doc.testplan['testplan']['testfile']

                is_changed = False
                for test_file in test_files_list:
                    old_test_file_name_regex = re.compile(old_test_file_name)
                    if re.findall(old_test_file_name_regex, test_file['file']):
                        test_file['file'] = new_test_file_name
                        test_file['extension'] = extFilename
                        is_changed = True
                        
                if is_changed:
                    file_content = doc.getRaw()
                    f_path_list = file_path.split('/')
                    path_file = '/'.join(f_path_list[:-1])
                    name_file = f_path_list[-1][:-4]
                    self.uploadFile(pathFile=path_file, 
                                    nameFile=name_file,
                                    extFile=ext_file_name,
                                    contentFile=file_content, 
                                    login=user_login, 
                                    project=project_id,
                                    overwriteFile=True, 
                                    createFolders=False, 
                                    lockMode=False,
                                    binaryMode=True, 
                                    closeAfter=False)

                    # notify all connected users of the change
                    data = ( 'test', ( "changed", {"modified-by": user_login, 
                                                   "path": file_path,
                                                   "project-id": project_id} ) )   
                    ESI.instance().notifyByUserAndProject(body=data, 
                                                          admin=True, 
                                                          monitor=True, 
                                                          tester=True, 
                                                          projectId=int(project_id))

                    # append the file modified to the list
                    updated_files_list.append( file_path )
                    
        return updated_files_list

    def getTestsForUpdate(self, listing, extFileName):
        """
        """
        tests_list = []

        extDict = {
            RepoManager.TEST_UNIT_EXT: [RepoManager.TEST_GLOBAL_EXT, RepoManager.TEST_PLAN_EXT],
            RepoManager.TEST_PLAN_EXT: [RepoManager.TEST_GLOBAL_EXT],
            RepoManager.TEST_SUITE_EXT: [RepoManager.TEST_GLOBAL_EXT, RepoManager.TEST_PLAN_EXT],
            'all': [ RepoManager.TEST_GLOBAL_EXT, 
                     RepoManager.TEST_PLAN_EXT, 
                     RepoManager.TEST_SUITE_EXT,
                     RepoManager.TEST_UNIT_EXT, 
                     ]
        }


        for test in listing:
            if test['type'] == 'file':
                ext_test = test['name'].split('.')[-1]
                req_exts = extDict[extFileName]
                if extFileName in extDict and ext_test in req_exts:
                    tests_list.append(test)
            else:
                if test['type'] == 'folder':
                    tests_list.append(test)
                    tests_list[-1]['content'] = (self.getTestsForUpdate(listing=test['content'],
                                                                        extFileName=extFileName))
        return tests_list

    def get_files_paths(self, tests_tree, file_path='/', exceptions=[]):
        """
        """
        list_path = []
        for test in tests_tree:
            f_path = file_path

            if test['type'] == 'file':
                # ignore specific files ?
                exception_detected = False
                for ex in exceptions:
                    if ex == '%s%s' % (f_path, test['name']):
                        exception_detected = True
                        break
                
                if exception_detected:
                    continue
                list_path.append('%s%s' % (f_path, test['name']))
            else:
                f_path += '%s/' % test['name']
                list_path += self.get_files_paths(test['content'], 
                                                  file_path=f_path,
                                                  exceptions=exceptions)
        return list_path

    # dbr13 <<

    def getVariablesFromDB(self, projectId=None):
        """
        Get test variables from database
        """
        sql_args = ()
        
        # get all users
        sql = """SELECT id, name, project_id"""
        if Settings.getInt( 'Database', 'test-environment-encrypted'):
            sql += """, AES_DECRYPT(value, ?) as value""" 
            sql_args += (Settings.get( 'Database', 'test-environment-password'),)
        else:
            sql += """, value"""
        sql += """ FROM `%s`""" % ( self.tb_variables )
        if projectId is not None:
            projectId = str(projectId)
            sql += """ WHERE project_id=?"""
            sql_args += (projectId,)
        sql += """ ORDER BY name"""
        success, dbRows = DbManager.instance().querySQL( query = sql, 
                                                         columnName=True,
                                                         args=sql_args )
        if not success: 
            self.error( "unable to read test environment table" )
            return (self.context.CODE_ERROR, "unable to test environment table")
            
        # new in v17 convert as json the result 
        for d in dbRows:
            try:
                d['value'] = json.loads( d['value'] )  
            except Exception:
                d['value'] = "Bad JSON" 
        # end of new
        
        return (self.context.CODE_OK, dbRows)
        
    def getVariableFromDB(self, projectId, variableName=None, variableId=None):
        """
        Get a specific variable from database
        """
        # init some shortcut
        projectId = str(projectId)
        sql_args = ()
        
        # get all users
        sql = """SELECT id, name, project_id"""
        if Settings.getInt( 'Database', 'test-environment-encrypted'):
            sql += """, AES_DECRYPT(value, ?) as value"""
            sql_args += (Settings.get( 'Database', 'test-environment-password'),)
        else:
            sql += """, value"""
        sql += """ FROM `%s`""" % ( self.tb_variables )
        sql += """ WHERE project_id=?"""
        sql_args += (projectId,)
        if variableName is not None:
            sql += """ AND name LIKE ?"""
            sql_args += ( "%%%s%%" % variableName,)
        if variableId is not None:
            variableId = str(variableId)
            sql += """ AND id=?"""
            sql_args += (variableId,)
        success, dbRows = DbManager.instance().querySQL( query = sql, 
                                                         columnName=True,
                                                         args=sql_args)
        if not success: 
            self.error( "unable to search test environment table" )
            return (self.context.CODE_ERROR, "unable to search variable in test environment table")

        # new in v17 convert as json the result 
        for d in dbRows:
            try:
                d['value'] = json.loads( d['value'] ) 
            except Exception:
                d['value'] = "Bad JSON"     
        # end of new
        return (self.context.CODE_OK, dbRows)
        
    def addVariableInDB(self, projectId, variableName, variableValue):
        """
        Add a variable in the database
        """
        # init some shortcut
        projectId = str(projectId)
        
        if ":" in variableName:
            return (self.context.CODE_ERROR, "bad variable name provided")
            
        # check if the name is not already used
        sql = """SELECT * FROM `%s` WHERE name=?""" % ( self.tb_variables )
        sql += """ AND project_id=?"""
        success, dbRows = DbManager.instance().querySQL( query = sql, 
                                                         columnName=True,
                                                         arg1=variableName.upper(),
                                                         arg2=projectId)
        if not success: 
            self.error( "unable to get variable by name" )
            return (self.context.CODE_ERROR, "unable to get variable by name")
        if len(dbRows): return (self.context.CODE_ALREADY_EXISTS, "this variable already exists")
        
        # good json ?
        try:
            json.loads(variableValue)
        except Exception:
            return (self.context.CODE_ERROR, "bad json value provided")
         
        # this name is free then create project
        sql = """INSERT INTO `%s`(`name`, `value`, `project_id` )""" % self.tb_variables
        if Settings.getInt( 'Database', 'test-environment-encrypted'):
            sql += """VALUES(?, AES_ENCRYPT(?, ?), ?)"""
            success, lastRowId = DbManager.instance().querySQL( query = sql, 
                                                                insertData=True,
                                                                arg1=variableName.upper(),
                                                                arg2=variableValue,
                                                                arg3=Settings.get( 'Database', 'test-environment-password'),
                                                                arg4=projectId)
        else:
            sql += """VALUES(?, ?, ?)"""
            success, lastRowId = DbManager.instance().querySQL( query = sql, 
                                                                insertData=True,
                                                                arg1=variableName.upper(),
                                                                arg2=variableValue,
                                                                arg3=projectId)
        if not success: 
            self.error("unable to insert variable")
            return (self.context.CODE_ERROR, "unable to insert variable")
        
        # new in v19, refresh the cache
        self.loadCacheVars()
        
        # refresh the context of all connected users
        self.context.refreshTestEnvironment()

        return (self.context.CODE_OK, "%s" % int(lastRowId) )
        
    def duplicateVariableInDB(self, variableId, projectId=None):
        """
        Duplicate a variable in database
        """
        # init some shortcut
        variableId = str(variableId)
        sql_args = ()
        
        # find variable by id
        sql = """SELECT * FROM `%s` WHERE  id=?""" % ( self.tb_variables)
        sql_args += (variableId,)
        if projectId is not None:
            projectId = str(projectId)
            sql += """ AND project_id=?"""
            sql_args += (projectId,)
            
        success, dbRows = DbManager.instance().querySQL( query = sql, 
                                                         columnName=True, 
                                                         args=sql_args  )
        if not success: 
            self.error( "unable to read variable id" )
            return (self.context.CODE_ERROR, "unable to read variable id")
        if not len(dbRows): return (self.context.CODE_NOT_FOUND, "this variable id does not exist")
        variable = dbRows[0]
        
        # duplicate variable
        newVarName = "%s-COPY#%s" % (variable['name'], uniqid())

        return self.addVariableInDB(projectId=variable["project_id"], 
                                    variableName=newVarName, 
                                    variableValue=variable["value"])
        
    def updateVariableInDB(self, variableId, variableName=None, 
                           variableValue=None, projectId=None):
        """
        Update the value of a variable in a database
        """
        # init some shortcut
        variableId = str(variableId)

        # find variable by id
        sql = """SELECT * FROM `%s` WHERE  id=?""" % ( self.tb_variables )
        success, dbRows = DbManager.instance().querySQL( query = sql, 
                                                         columnName=True,
                                                         arg1=variableId)
        if not success: 
            self.error( "unable to read variable id" )
            return (self.context.CODE_ERROR, "unable to read variable id")
        if not len(dbRows): return (self.context.CODE_NOT_FOUND, "this variable id does not exist")
        
        sql_values = []
        sql_args = ()
        if variableName is not None:
            sql_values.append( """name=?""" )
            sql_args += (variableName.upper(),)
        if variableValue is not None:
            # good json ?
            try:
                json.loads(variableValue)
            except Exception:
                return (self.context.CODE_ERROR, "bad json value provided")
         
            if Settings.getInt( 'Database', 'test-environment-encrypted'):
                sql_values.append( """value=AES_ENCRYPT(?, ?)""" )
                sql_args += (variableValue, Settings.get( 'Database', 'test-environment-password'))
            else:
                sql_values.append( """value=?""" )
                sql_args += (variableValue,)
        if projectId is not None:
            projectId = str(projectId)
            sql_values.append( """project_id=?""" )
            sql_args += (projectId,)
            
        # update
        if len(sql_values):
            sql_args += (variableId,)
            sql = """UPDATE `%s` SET %s WHERE id=?""" % (   self.tb_variables, ','.join(sql_values))
            success, _ = DbManager.instance().querySQL( query = sql, args=sql_args )
            if not success: 
                self.error("unable to update variable")
                return (self.context.CODE_ERROR, "unable to update variable")
        
        # new in v19, refresh the cache
        self.loadCacheVars()
        
        # refresh the context of all connected users
        self.context.refreshTestEnvironment()
        
        return (self.context.CODE_OK, "" )
        
    def delVariableInDB(self, variableId, projectId=None):
        """
        Delete a variable in database
        """
        # init some shortcut
        variableId = str(variableId)
        sql_args = ()
        
        # check if the name is not already used
        sql = """SELECT * FROM `%s` WHERE id=?""" % ( self.tb_variables )
        sql_args += (variableId,)
        if projectId is not None:
            projectId = str(projectId)
            sql += """ AND project_id=?"""
            sql_args += (projectId,)
            
        success, dbRows = DbManager.instance().querySQL( query = sql, 
                                                         columnName=True, 
                                                         args=sql_args  )
        if not success: 
            self.error( "unable to get variable by id" )
            return (self.context.CODE_ERROR, "unable to get variable by id")
        if not len(dbRows): return (self.context.CODE_NOT_FOUND, "variable id provided does not exist")
        
        # delete from db
        sql_args = ()
        sql = """DELETE FROM `%s` WHERE  id=?""" % ( self.tb_variables )
        sql_args += (variableId,)
        if projectId is not None:
            projectId = str(projectId)
            sql += """ AND project_id=?"""
            sql_args += (projectId,)
            
        success, _ = DbManager.instance().querySQL( query = sql, args=sql_args  )
        if not success: 
            self.error( "unable to remove variable by id" )
            return (self.context.CODE_ERROR, "unable to remove variable by id")
           
        # new in v19, refresh the cache
        self.loadCacheVars()
        
        # refresh the context of all connected users
        self.context.refreshTestEnvironment()
        
        return (self.context.CODE_OK, "" )
        
    def delVariablesInDB(self, projectId):
        """
        Delete all variables in database
        """
        # init some shortcut
        projectId = str(projectId)
        sql_args = ()
        
        # delete from db
        sql = """DELETE FROM `%s` WHERE  project_id=?""" % ( self.tb_variables )
        sql_args += (projectId,)
        success, _ = DbManager.instance().querySQL( query = sql, args=sql_args  )
        if not success: 
            self.error( "unable to reset variables" )
            return (self.context.CODE_ERROR, "unable to reset variables")
            
        # new in v19, refresh the cache
        self.loadCacheVars()
        
        # refresh the context of all connected users
        self.context.refreshTestEnvironment()
        
        return (self.context.CODE_OK, "" )


RepoTestsMng = None
def instance ():
    """
    Returns the singleton

    @return:
    @rtype:
    """
    return RepoTestsMng

def initialize (context):
    """
    Instance creation
    """
    global RepoTestsMng
    RepoTestsMng = RepoTests(context=context)

def finalize ():
    """
    Destruction of the singleton
    """
    global RepoTestsMng
    if RepoTestsMng:
        RepoTestsMng = None