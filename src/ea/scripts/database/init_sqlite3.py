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


import sys
sys.path.insert(0, '../../../' )

from ea.libs import Settings
from common_bdd import querySQL

# initialize settings module to read the settings.ini file
Settings.initialize(path="./")


def create_sqlite3_model():
    querySQL( query = "")
    querySQL( query = """
                    CREATE TABLE IF NOT EXISTS `users` (
                      `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                      `login` varchar(50) NOT NULL,
                      `password` varchar(200) NOT NULL,
                      `administrator` INT,
                      `leader` INT,
                      `developer` INT,
                      `tester` INT,
                      `system` INT,
                      `email` varchar(200) NOT NULL,
                      `lang` varchar(50) NOT NULL,
                      `style` varchar(50) NOT NULL,
                      `active` INT,
                      `default` INT,
                      `online` INT,
                      `cli` INT,
                      `gui` INT,
                      `web` INT,
                      `notifications` varchar(200) NOT NULL,
                      `defaultproject` INT,
                      `apikey_id` varchar(200),
                      `apikey_secret` varchar(200)
                    );
                    """)
    querySQL( query = """
                    CREATE TABLE IF NOT EXISTS `tasks-history` (
                        `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        `eventtype` INT not null,
                        `eventargs` VARCHAR(50),
                        `eventtime` VARCHAR(20),
                        `eventname` VARCHAR(200),
                        `eventauthor` VARCHAR(50),
                        `realruntime` VARCHAR(20),
                        `eventduration` VARCHAR(20),
                        `eventresult` VARCHAR(20),
                        `projectid` INT
                    ) ;
                    """)
    querySQL( query = """
                    CREATE TABLE IF NOT EXISTS `config` (
                        `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        `opt` TEXT,
                        `value` TEXT
                    );
                    """)
    querySQL( query = """
                    CREATE TABLE IF NOT EXISTS `projects` (
                        `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        `name` TEXT,
                        `active` INT,
                        `description` TEXT
                    );
                    """)
    querySQL( query = """
                    CREATE TABLE IF NOT EXISTS `relations-projects` (
                        `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        `user_id` INT,
                        `project_id` INT
                    );
                    """)
    querySQL( query = """
                    CREATE TABLE IF NOT EXISTS `test-environment` (
                        `id` INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        `name` TEXT,
                        `value` TEXT,
                        `project_id` INT
                    );
                    """)
                    