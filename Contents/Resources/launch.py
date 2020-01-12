#!/usr/bin/env python3

""" 
 @file
 @brief This file is used to launch OpenShot
 @author Jonathan Thomas <jonathan@openshot.org>
 @author Noah Figg <eggmunkee@hotmail.com>
 
 @mainpage OpenShot Video Editor 2.0
 
 Welcome to the OpenShot Video Editor 2.0 PyQt5 documentation. OpenShot was developed to
 make high-quality video editing and animation solutions freely available to the world. With a focus
 on stability, performance, and ease-of-use, we believe OpenShot is the best cross-platform,
 open-source video editing application in the world!
 
 This documentation is auto-generated by Doxygen, using the doxypy Python filter. If you are 
 interested in how OpenShot Video Editor is designed, feel free to dive in, because this 
 documentation was built just for you. If you are not a developer, please feel free to visit
 our main website (http://www.openshot.org/download/), and download a copy today for Linux, Mac, or Windows. 

 @section LICENSE
 
 Copyright (c) 2008-2018 OpenShot Studios, LLC
 (http://www.openshotstudios.com). This file is part of
 OpenShot Video Editor (http://www.openshot.org), an open-source project
 dedicated to delivering high quality video editing and animation solutions
 to the world.
 
 OpenShot Video Editor is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.
 
 OpenShot Video Editor is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.
 
 You should have received a copy of the GNU General Public License
 along with OpenShot Library.  If not, see <http://www.gnu.org/licenses/>.
 """

import sys
from argparse import ArgumentParser, REMAINDER

try:
    from classes import info
    print("Loaded modules from current directory: %s" % info.PATH)
except ImportError:
    import openshot_qt
    sys.path.append(openshot_qt.OPENSHOT_PATH)
    from classes import info
    print("Loaded modules from installed directory: %s" % info.PATH)

from classes.app import OpenShotApp
from classes.logger import log, reroute_output
from classes.language import get_all_languages


def main():
    """"Initialize settings (not implemented) and create main window/application."""

    parser = ArgumentParser(description = 'OpenShot version ' + info.SETUP['version'])
    parser.add_argument('-l', '--lang', action='store',
                        help='language code for interface (overrides '
                        'preferences and system environment)')
    parser.add_argument('--list-languages', dest='list_languages',
                        action='store_true', help='List all language '
                        'codes supported by OpenShot')
    parser.add_argument('-V', '--version', action='store_true')
    parser.add_argument('remain', nargs=REMAINDER)

    args = parser.parse_args()

    # Display version and exit (if requested)
    if args.version:
        print("OpenShot version %s" % info.SETUP['version'])
        sys.exit()

    if args.list_languages:
        print("Supported Languages:")
        for lang in get_all_languages():
            print("  {:>12}  {}".format(lang[0],lang[1]))
        sys.exit()

    if args.lang:
        if args.lang in info.SUPPORTED_LANGUAGES:
            info.CMDLINE_LANGUAGE = args.lang
        else:
            print("Unsupported language '{}'! (See --list-languages)".format(args.lang))
            sys.exit(-1)

    reroute_output()

    log.info("------------------------------------------------")
    log.info("   OpenShot (version %s)" % info.SETUP['version'])
    log.info("------------------------------------------------")

    # Create Qt application, pass any unprocessed arguments
    argv = [sys.argv[0]]
    for arg in args.remain:
        argv.append(arg)
    app = OpenShotApp(argv)

    # Run and return result
    sys.exit(app.run())


if __name__ == "__main__":
    main()