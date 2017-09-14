#!/usr/bin/python
#
# Copyright 2017 Yoann Gini
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""See docstring for MacPortPackager class"""

import os.path
import socket
import FoundationPlist
import subprocess
import xml.etree.ElementTree as ET

from autopkglib import Processor, ProcessorError


AUTO_PKG_SOCKET = "/var/run/autopkgmacports"


__all__ = ["MacPortPackager"]


class MacPortPackager(Processor):
    """Calls autopkgmacports to create a package."""
    description = __doc__
    input_variables = {
        "pkg_request": {
            "required": True,
            "description": (
                "A package request dictionary. See "
                "Code/autopkgmacports/autopkgmacports for more details.")
        },
    }
    output_variables = {
        "pkg_path": {
            "description": "The created package.",
        }
    }

    def find_path_for_relpath(self, relpath):
        '''Searches for the relative path.
        Search order is:
            RECIPE_CACHE_DIR
            RECIPE_DIR
            PARENT_RECIPE directories'''
        cache_dir = self.env.get('RECIPE_CACHE_DIR')
        recipe_dir = self.env.get('RECIPE_DIR')
        search_dirs = [cache_dir, recipe_dir]
        if self.env.get("PARENT_RECIPES"):
            # also look in the directories containing the parent recipes
            parent_recipe_dirs = list(
                set([os.path.dirname(item)
                     for item in self.env["PARENT_RECIPES"]]))
            search_dirs.extend(parent_recipe_dirs)
        for directory in search_dirs:
            test_item = os.path.join(directory, relpath)
            if os.path.exists(test_item):
                return os.path.normpath(test_item)

        raise ProcessorError("Can't find %s" % relpath)

    def package(self):
        '''Build a packaging request, send it to the autopkgmacports and get the
        constructed package.'''

        # clear any pre-exising summary result
        if 'pkg_creator_summary_result' in self.env:
            del self.env['pkg_creator_summary_result']

        request = self.env["pkg_request"]
        if not 'pkgdir' in request:
            request['pkgdir'] = self.env['RECIPE_CACHE_DIR']

        # Convert relative paths to absolute.
        for key, value in request.items():
            if key in ("pkgdir"):
                if value and not value.startswith("/"):
                    # search for it
                    request[key] = self.find_path_for_relpath(value)

        # Send packaging request.
        try:
            self.output("Connecting")
            self.connect()
            self.output("Sending packaging request")
            self.env["new_package_request"] = True
            pkg_path = self.send_request(request)
        finally:
            self.output("Disconnecting")
            self.disconnect()

        # Return path to pkg.
        self.env["pkg_path"] = pkg_path
        self.env["pkg_creator_summary_result"] = {
            'summary_text': 'The following packages were built:',
            'report_fields': ['pkg_path'],
            'data': {
                'pkg_path': pkg_path
            }
        }

    def connect(self):
        '''Connect to autopkgmacports'''
        try:
            #pylint: disable=attribute-defined-outside-init
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            #pylint: enable=attribute-defined-outside-init
            self.socket.connect(AUTO_PKG_SOCKET)
        except socket.error as err:
            raise ProcessorError(
                "Couldn't connect to autopkgmacports: %s" % err.strerror)

    def send_request(self, request):
        '''Send a packaging request to the autopkgmacports'''
        self.socket.send(FoundationPlist.writePlistToString(request))
        with os.fdopen(self.socket.fileno()) as fileref:
            reply = fileref.read()

        if reply.startswith("OK:"):
            return reply.replace("OK:", "").rstrip()

        errors = reply.rstrip().split("\n")
        if not errors:
            errors = ["ERROR:No reply from server (crash?), check system logs"]
        raise ProcessorError(
            ", ".join([s.replace("ERROR:", "") for s in errors]))

    def disconnect(self):
        '''Disconnect from the autopkgmacports'''
        self.socket.close()

    def main(self):
        '''Package something!'''
        self.package()


if __name__ == '__main__':
    PROCESSOR = MacPortPackager()
    PROCESSOR.execute_shell()

