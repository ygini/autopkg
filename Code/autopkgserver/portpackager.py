#!/usr/bin/python
#
# Copyright 2010-2012 Per Olofsson
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


import os
import plistlib
import stat
import shutil
import subprocess
import re
import tempfile
import pwd
import grp
import fnmatch

from xml.parsers.expat import ExpatError

__all__ = [
    'PortPackager',
    'PortPackagerError'
]


class PortPackagerError(Exception):
    pass

class PortPackager(object):
    """Create an Apple installer package.

    Must be run as root."""

    re_portname = re.compile(r'^[a-z0-9][a-z0-9._\-]*$', re.I)
    re_variant = re.compile(r'^[a-z0-9][a-z0-9._\-]*$', re.I)
    re_version = re.compile(r'^@[0-9.]*[0-9_]*$', re.I)

    def __init__(self, log, request, uid, gid):
        """Arguments:

        log     A logger instance.
        request A request in plist format.
        uid     The UID of the user that made the request.
        gid     The GID of the user that made the request.
        """

        self.log = log
        self.request = request
        self.uid = uid
        self.gid = gid
        self.tmproot = None

    def package(self):
        """Main method."""

        try:
            self.verify_request()
            return self.create_pkg()
        finally:
            self.cleanup()

    def verify_dir_and_owner(self, path, uid):
        try:
            info = os.lstat(path)
        except OSError as e:
            raise PackagerError("Can't stat %s: %s" % (path, e))
        if info.st_uid != uid:
            raise PackagerError("%s isn't owned by %d" % (path, uid))
        if stat.S_ISLNK(info.st_mode):
            raise PackagerError("%s is a soft link" % path)
        if not stat.S_ISDIR(info.st_mode):
            raise PackagerError("%s is not a directory" % path)

    def verify_request(self):
        """Verify that the request is valid."""

        self.log.debug("Verifying packaging request")

        self.verify_dir_and_owner(self.request.pkgdir, self.uid)
        self.log.debug("pkgdir ok")

        # Check name.
        if not self.re_portname.search(self.request.port):
            raise PortPackagerError("Invalid package name")
        self.log.debug("pkgname ok")

        # Check variants.
        if 'variants' in self.request:
            for variant in self.request.variants:
                if not self.re_variant.search(variant):
                    raise PortPackagerError("Invalid package variant")
            self.log.debug("Variants ok")

        # Check version.
        if 'version' in self.request:
            if len(self.request.version) > 40:
                raise PortPackagerError("Version too long")
            components = self.request.version.split(".")
            if len(components) < 1:
                raise PortPackagerError("Invalid version \"%s\"" % self.request.version)
            for comp in components:
                if not self.re_version.search(comp):
                    raise PortPackagerError("Invalid version component \"%s\"" % comp)
            self.log.debug("version ok")

        # TODO: Include a test of  existance for package + version + variants

        self.log.info("Packaging request verified")

    def cmd_output(self, cmd):
        '''Outputs a stdout, stderr tuple from command output using a Popen'''
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        if err:
            self.log.debug("WARNING: errors from command '%s':" % ", ".join(cmd))
            self.log.debug(err)
        return (out, err)

    def clean_port(self):
        cmd = ["/opt/local/bin/port",
               "clean",
               "--all",
               self.request.port]

        try:
            p = subprocess.Popen(cmd,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
            (out, err) = p.communicate()
        except OSError as e:
            raise PortPackagerError(
                "Port clean failed with error code %d: %s"
                % (e.errno, e.strerror))
        if p.returncode != 0:
            raise PortPackagerError("Port clean failed with exit code %d: %s" % (
                p.returncode,
                " ".join(str(err).split())))

    def find_work_path(self):
        cmd = ["/opt/local/bin/port",
               "work",
               self.request.port]
        out, err = self.cmd_output(cmd)

        return out.splitlines()[0]

    def find_mpkg_name(self):

        for file in os.listdir(self.find_work_path()):
            if fnmatch.fnmatch(file, self.request.port+'-*.mpkg'):
                return file

    def create_pkg(self):
        self.log.info("Creating package")

        self.clean_port()

        cmd = ["/opt/local/bin/port",
                "mpkg",
                self.request.port]
        if 'version' in self.request:
            cmd.extend([self.request.version])
        if 'variants' in self.request:
            cmd.extend(self.request.variants)

        # Execute pkgbuild.
        try:
            p = subprocess.Popen(cmd,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
            (out, err) = p.communicate()
        except OSError as e:
            raise PortPackagerError(
                "Port package execution failed with error code %d: %s"
                % (e.errno, e.strerror))
        if p.returncode != 0:
            raise PortPackagerError("Port package with exit code %d: %s" % (
                                 p.returncode,
                                 " ".join(str(err).split())))

        pkgname = self.find_mpkg_path()
        pkgpath = self.request.pkgdir+'/'+pkgname
        os.rename(self.find_work_path()+'/'+pkgname, pkgpath)
        os.chown(pkgpath, self.uid, self.gid)
        self.log.info("Created package at %s" % pkgpath)
        return pkgpath

    def cleanup(self):
        """Clean up resources."""
        # No port clean up at this time, otherwise it will also remove the mpkg
        # self.clean_port()

