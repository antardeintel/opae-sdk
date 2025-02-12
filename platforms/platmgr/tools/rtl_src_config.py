#!/usr/bin/env python3

#
# Consume a file with a list of source files, include paths and preprocessor
# definitions. Emit either Quartus or simulator commands to load the sources.
#
# The configuration can be recursive, with configuration file loading another.
# See the output of --help for details.
#

import argparse
import os
import sys
import subprocess
import re


def errorExit(msg):
    sys.stderr.write("\nrtl_src_config error: " + msg + "\n")
    sys.exit(1)


# Suffix to Quartus tag.
quartus_tag_map = {
    '.v':    'VERILOG_FILE',
    '.sv':   'SYSTEMVERILOG_FILE',
    '.vh':   'SYSTEMVERILOG_FILE',
    '.svh':  'SYSTEMVERILOG_FILE',
    '.vhd':  'VHDL_FILE',
    '.vhdl': 'VHDL_FILE',
    '.sdc':  'SDC_FILE',
    '.qsys': 'QSYS_FILE',
    '.ip':   'IP_FILE',
    '.qip':  'QIP_FILE',
    '.json': 'MISC_FILE',
    '.tcl':  'SOURCE_TCL_SCRIPT_FILE',
    '.stp':  'USE_SIGNALTAP_FILE',
    '.hex':  'MIF_FILE',
    '.mif':  'MIF_FILE'
}

# QSYS-only tags.
qsys_tag_map = {
    '.qsys': 'QSYS_FILE',
    '.qip':  'QIP_FILE',
    '.ip':   'IP_FILE'
}

tcl_tag_map = {
    '.tcl':  'SOURCE_TCL_SCRIPT_FILE'
}

# QSYS ipx tag.
qsys_ipx_tag_map = {
    '.ipx':  'IPX_FILE'
}

# JSON-only tags.
json_tag_map = {
    '.json': 'MISC_FILE'
}

# Suffixes to emit for simulation targets.  This is a subset of the
# Quartus map.
sim_vlog_tag_map = {
    '.v':    'VERILOG_FILE',
    '.sv':   'SYSTEMVERILOG_FILE',
    '.vh':   'SYSTEMVERILOG_FILE',
    '.svh':  'SYSTEMVERILOG_FILE',
    '.json': 'MISC_FILE'
}
sim_vhdl_tag_map = {
    '.vhd':  'VHDL_FILE',
    '.vhdl': 'VHDL_FILE'
}


def validateTag(filename):
    _basename, ext = os.path.splitext(filename)
    ext = ext.lower()

    if (ext not in quartus_tag_map and
            ext not in qsys_tag_map and
            ext not in tcl_tag_map and
            ext not in qsys_ipx_tag_map and
            ext not in json_tag_map and
            ext not in sim_vlog_tag_map and
            ext not in sim_vhdl_tag_map):
        errorExit(
            "unrecognized file extension '{0}' ({1})".format(ext, filename))


def lookupTag(filename, db):
    _basename, ext = os.path.splitext(filename)
    ext = ext.lower()

    if (ext not in db):
        return None
    else:
        return db[ext]


#
# Given a list of directives, emit the configuration.
#
def emitCfg(opts, cfg):
    # Filtering for specific file types?
    file_type_filter = opts.qsys or opts.ipx or opts.json or opts.tcl

    rel_prefix = ''
    if (not file_type_filter):
        if (not opts.sim and not opts.abs):
            # For Quartus, generate a Tcl variable for relative paths
            print('set THIS_DIR [file dirname [info script]]\n')
            rel_prefix = '${THIS_DIR}/'

        # First emit all preprocessor configuration
        for c in cfg:
            if ("+define+" == c[:8]):
                if (opts.sim_vlog):
                    print(c)
                elif (opts.sim_vhdl):
                    None
                else:
                    print('set_global_assignment -name VERILOG_MACRO "' +
                          c[8:] + '"')

        # Emit all include directives
        for c in cfg:
            if ("+incdir+" == c[:8]):
                if (opts.sim_vlog):
                    print(c)
                elif (opts.sim_vhdl):
                    None
                else:
                    print('set_global_assignment -name SEARCH_PATH "{0}{1}"'
                          .format(rel_prefix, c[8:]))

    # Emit sources and Quartus/simulator includes
    for c in cfg:
        # Parse cmd:value
        try:
            cmd, value = c.split(':', 1)
            has_cmd = True
        except ValueError:
            has_cmd = False

        if ("+" == c[:1]):
            # Directive handled already
            None
        elif (has_cmd and ("SI" == cmd or "SI_VLOG" == cmd)):
            # Simulator include
            if (lookupTag(value, tcl_tag_map) and (opts.sim_vlog or
                                                   opts.tcl)):
                print(value)
            elif (opts.sim_vlog):
                print("-F " + value)
        elif (has_cmd and ("SI_VHDL" == cmd)):
            # Simulator include
            if (lookupTag(value, tcl_tag_map) and (opts.sim_vhdl or
                                                   opts.tcl)):
                print(value)
            elif (opts.sim_vhdl):
                print("-F " + value)
        elif (has_cmd and ("QI" == cmd)):
            # Quartus include
            if (not opts.sim and not file_type_filter):
                print('source "{0}{1}"'.format(rel_prefix, value))
        else:
            validateTag(c)
            tag = lookupTag(c, quartus_tag_map)

            if (opts.sim_vlog):
                if (lookupTag(c, sim_vlog_tag_map)):
                    print(c)
            elif (opts.sim_vhdl):
                if (lookupTag(c, sim_vhdl_tag_map)):
                    print(c)
            elif (opts.json):
                if (lookupTag(c, json_tag_map)):
                    print(c)
            elif (opts.qsys):
                if (lookupTag(c, qsys_tag_map)):
                    print(c)
            elif (opts.ipx):
                if (lookupTag(c, qsys_ipx_tag_map)):
                    print(c)
            elif (opts.tcl):
                if (lookupTag(c, tcl_tag_map)):
                    print(c)
            elif (tag is not None):
                # We assume that all bare .tcl files are part of Qsys
                # and ignore them in Quartus flows. To get a .tcl
                # file in Quartus, use QI:<path to>.tcl.
                if (tag != 'SOURCE_TCL_SCRIPT_FILE'):
                    print('set_global_assignment -name {0} "{1}{2}"'
                          .format(tag, rel_prefix, c))


#
# Detect paths in configuration directives and make them relative to the target
# directory.
#
def fixRelPath(opts, c, config_dir, tgt_dir):
    if (len(c) == 0):
        return c
    if ("+define+" == c[:8]):
        return c

    # Everything else ends in a path, though check for prefixes
    if ("+incdir+" == c[:8]):
        prefix = "+incdir+"
        c = c[8:]
    else:
        prefix = ""
        split = c.split(':', 1)
        if (len(split) <= 1):
            # Is the entry a directory?  If so, canonicalize it as +incdir+.
            if (os.path.isdir(os.path.join(config_dir, c))):
                prefix = "+incdir+"
        else:
            prefix = split[0] + ":"
            c = split[1]

    # Transform path first to be relative to the configuration file.
    # Then transform it to be relative to the target directory.
    p = os.path.relpath(os.path.join(config_dir, c), tgt_dir)
    if (opts.abs):
        p = os.path.abspath(p)

    return prefix + p


#
# Recursive parse of configuration files.
#
def parseConfigFile(opts, cfg_file_name, tgt_dir):
    if (len(cfg_file_name) == 0):
        return []

    cfg = []

    try:
        dir = os.path.dirname(cfg_file_name)
        with open(cfg_file_name) as cfg_file:
            for c in cfg_file:
                c = c.strip()
                # Drop comments
                c = c.split('#', 1)[0]

                # Replace environment variables
                if ('OPAE_PLATFORM_FPGA_FAMILY' in c and
                        'OPAE_PLATFORM_FPGA_FAMILY' not in os.environ):
                    # The source requires version-specific Qsys and the
                    # tag has not yet been determined.
                    addDefaultFpgaFamily(opts)

                if ('QUARTUS_VERSION' in c and
                        ('QUARTUS_VERSION' not in os.environ or
                         'QUARTUS_VERSION_MAJOR' not in os.environ)):
                    getQuartusVersion(opts)

                c = os.path.expandvars(c)

                # Recursive include?
                if (c[:2] == 'C:'):
                    cfg += parseConfigFile(
                        opts, os.path.join(dir, c[2:]), tgt_dir)
                elif (len(c)):
                    # Append to the configuration list
                    cfg.append(fixRelPath(opts, c, dir, tgt_dir))

    except IOError:
        errorExit("failed to open file ({0})".format(cfg_file_name))

    return cfg


#
# The hw/lib directory of a platform's release.  We find the hw/lib
# directory using the following search rules, in decreasing priority:
#
#   1. --lib argument to this script.
#   2. BBS_LIB_PATH:
#        We used to document this environment variable as the primary
#        pointer for scripts.
#   3. OPAE_PLATFORM_ROOT:
#        This variable replaces all pointers to a release directory,
#        starting with the discrete platform's 1.1 release.  The
#        hw/lib directory is ${OPAE_PLATFORM_ROOT}/hw/lib.
#
def getHWLibPath(opts):
    if (opts.lib is not None):
        hw_lib_dir = opts.lib
    elif ('BBS_LIB_PATH' in os.environ):
        # Legacy variable, shared with afu_sim_setup and HW releases
        hw_lib_dir = os.environ['BBS_LIB_PATH'].rstrip('/')
    elif ('OPAE_PLATFORM_ROOT' in os.environ):
        # Currently documented variable, pointing to a platform release
        hw_lib_dir = os.path.join(os.environ['OPAE_PLATFORM_ROOT'].rstrip('/'),
                                  'hw/lib')
    else:
        errorExit("Release hw/lib directory must be specified with " +
                  "OPAE_PLATFORM_ROOT, BBS_LIB_PATH or --lib")

    # Confirm that the path looks reasonable
    if (not os.path.exists(os.path.join(hw_lib_dir,
                                        'fme-platform-class.txt'))):
        errorExit("{0} is not a release hw/lib directory".format(hw_lib_dir))

    return hw_lib_dir


#
# Qsys requires source files that are specific to both FPGA technology and
# Quartus version.  We automatically define OPAE_PLATFORM_FPGA_FAMILY as an
# environment variable, which may be used in source specification to choose
# the right code.
#
def addDefaultFpgaFamily(opts):
    # Define an environment variable for Qsys versions based on the
    # platform.

    if ('OPAE_PLATFORM_FPGA_FAMILY' not in os.environ):
        try:
            # Get the FPGA technology tag using afu_platform_info
            cmd = 'afu_platform_info --key=fpga-family '

            # What's the platform name?
            plat_class_file = os.path.join(getHWLibPath(opts),
                                           'fme-platform-class.txt')
            with open(plat_class_file) as f:
                cmd += f.read().strip()

            proc = subprocess.Popen(cmd, shell=True,
                                    stdout=subprocess.PIPE)
            for line in proc.stdout:
                line = line.decode('ascii').strip()
                os.environ['OPAE_PLATFORM_FPGA_FAMILY'] = line
            errcode = proc.wait()
            if (errcode):
                errorExit("failed to set OPAE_PLATFORM_FPGA_FAMILY")

            if (not opts.quiet):
                sys.stderr.write(
                    "Set OPAE_PLATFORM_FPGA_FAMILY to {0}\n".format(
                        os.environ['OPAE_PLATFORM_FPGA_FAMILY']))
        except Exception as e:
            errorExit("failed to set OPAE_PLATFORM_FPGA_FAMILY ({0})".format(
                str(e)))


#
# Invoke Quartus to load its major version number.
#
def getQuartusVersion(opts):
    if ('QUARTUS_VERSION' not in os.environ or
            'QUARTUS_VERSION_MAJOR' not in os.environ):
        try:
            # Get the Quartus major version number
            proc = subprocess.Popen('quartus_sh --version', shell=True,
                                    stdout=subprocess.PIPE)
            ok = False
            for line in proc.stdout:
                line = line.decode('ascii').strip()
                if (line[:7] == 'Version'):
                    ok = True

                    # Just the major version number
                    maj = re.sub(r'\D*(\d*)\..*', r'\1', line)
                    os.environ['QUARTUS_VERSION_MAJOR'] = maj
                    # Major.minor version
                    maj_min = re.sub(r'\D*(\d*\.\d*)\..*', r'\1', line)
                    os.environ['QUARTUS_VERSION'] = maj_min

            errcode = proc.wait()
            if (errcode or not ok):
                errorExit("Failed to compute QUARTUS_VERSION")

            if (not opts.quiet):
                sys.stderr.write(
                    "Set QUARTUS_VERSION to {0}\n".format(
                        os.environ['QUARTUS_VERSION']))
                sys.stderr.write(
                    "Set QUARTUS_VERSION_MAJOR to {0}\n".format(
                        os.environ['QUARTUS_VERSION_MAJOR']))
        except Exception as e:
            errorExit(str(e))


def main(args=None):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Emit RTL source list for Quartus or simulation " +
                    "given a configuration file.",
        epilog='''\
The configuration file is a list of source file names and configuration
directives.  The suffix of a file indicates its type and Quartus type
tags are emitted automatically for supported suffixes.  Some file types
are ignored, depending on the build target.  For example, SDC files are
ignored when constructing a list for simulation.

Environment variables in file paths are substituted as a configuration
file is loaded.  Several environment variables are defined automatically,
including OPAE_PLATFORM_FPGA_FAMILY (the value output by "afu_platform_info
--key=fpga-family"), QUARTUS_VERSION_MAJOR (e.g. 18) and QUARTUS_VERSION
(e.g. 18.1).

Files should be specified one per line in the configuration file.  A few
prefixes are treated specially.  Most are directives supported by Verilog
simulation tools.  In --qsf mode, these directives are transformed into
Quartus commands.  The following special syntax is supported:

  +incdir+<path>    Add include directory to the build-time search path.
                    Paths that are directories, even without +incdir+ are
                    also treated as include directives.

  +define+<X>       Define preprocessor variable.

  SI:<file>         Emit a directive to include <file> in the Verilog
  SI_VLOG:<file>    simulator configuration (the -F directive). The
                    request is ignored when the target is Quartus.
                    SI and SI_VLOG are synonyms.

  SI_VHDL:<file>    Emit a directive to include <file> in the VHDL
                    simulator configuration. SI_VHDL is the analog of
                    SI_VLOG for VHDL.

  QI:<file>         The equivalent of SI, but for Quartus.  A "source"
                    command is emitted.

These commands affect script parsing:

  C:<file>          Recursively parse <file> as a configuration file,
                    including it as though it were part of the current
                    script.

  # <comment>       All text following a '#' is ignored.''')

    parser.add_argument("config_file",
                        help="""Configuration file containing RTL source file
                                paths, preprocessor variable settings, etc.""")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sim",
                       action="store_true",
                       help="""Emit a configuration for Verilog RTL
                               simulation.""")
    group.add_argument("--sim-vlog",
                       action="store_true",
                       help="""Synonym for --sim.""")
    group.add_argument("--sim-vhdl",
                       action="store_true",
                       help="""Emit a configuration for VHDL RTL
                               simulation.""")
    group.add_argument("--qsf",
                       action="store_true",
                       help="""Emit a configuration for Quartus.""")
    group.add_argument("--qsys",
                       action="store_true",
                       help="""Emit only QSYS and IP file names.""")
    group.add_argument("--tcl",
                       action="store_true",
                       help="""Emit only TCL file names.""")
    group.add_argument("--ipx",
                       action="store_true",
                       help="""Emit only QSYS IPX file names.""")
    group.add_argument("--json",
                       action="store_true",
                       help="""Emit only JSON file names.""")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("-r", "--rel",
                       default=os.getcwd(),
                       help="""Convert paths relative to directory.""")
    group.add_argument("-a", "--abs",
                       action="store_true",
                       help="""Convert paths so they are absolute.""")

    # Verbose/quiet
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output")
    group.add_argument(
        "-q", "--quiet", action="store_true", help="Reduce output")

    parser.add_argument('-l', '--lib', default=None,
                        help="""FPGA platform release hw/lib directory.  If
                                not specified, the environment variables
                                OPAE_FPGA_HW_LIB and then BBS_LIB_PATH are
                                checked.""")

    opts = parser.parse_args(args)
    # Treat --sim and --sim-vlog as synonyms
    if opts.sim or opts.sim_vlog:
        opts.sim = True
        opts.sim_vlog = True
    # Now that opts.sim_vlog is set, enable opts.sim for any simulation
    if opts.sim_vhdl:
        opts.sim = True

    cfg = parseConfigFile(opts, opts.config_file, opts.rel)

    emitCfg(opts, cfg)


if __name__ == '__main__':
    main()
