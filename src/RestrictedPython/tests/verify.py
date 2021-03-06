##############################################################################
#
# Copyright (c) 2003 Zope Foundation and Contributors.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE
#
##############################################################################
"""Verify simple properties of bytecode.

Some of the transformations performed by the RestrictionMutator are
tricky.  This module checks the generated bytecode as a way to verify
the correctness of the transformations.  Violations of some
restrictions are obvious from inspection of the bytecode.  For
example, the bytecode should never contain a LOAD_ATTR call, because
all attribute access is performed via the _getattr_() checker
function.
"""

import dis
import types
import warnings


def verify(code):
    """Verify all code objects reachable from code.

    In particular, traverse into contained code objects in the
    co_consts table.
    """
    warnings.warn(
        "RestrictedPython.test.verify is deprecated and will be gone soon."
        "verify(<code>) tests on byte code level, which did not make sense"
        "with new implementation which is Python Implementation independend.",
        category=PendingDeprecationWarning,
        stacklevel=1
    )
    verifycode(code)
    for ob in code.co_consts:
        if isinstance(ob, types.CodeType):
            verify(ob)


def verifycode(code):
    try:
        _verifycode(code)
    except:
        dis.dis(code)
        raise


def _verifycode(code):
    line = code.co_firstlineno
    # keep a window of the last three opcodes, with the most recent first
    window = (None, None, None)
    with_context = (None, None)

    for op in disassemble(code):
        if op.line is not None:
            line = op.line
        if op.opname.endswith("LOAD_ATTR"):
            # All the user code that generates LOAD_ATTR should be
            # rewritten, but the code generated for a list comp
            # includes a LOAD_ATTR to extract the append method.
            # Another exception is the new-in-Python 2.6 'context
            # managers', which do a LOAD_ATTR for __exit__ and
            # __enter__.
            if op.arg == "__exit__":
                with_context = (op, with_context[1])
            elif op.arg == "__enter__":
                with_context = (with_context[0], op)
            elif not ((op.arg == "__enter__" and
                       window[0].opname == "ROT_TWO" and
                       window[1].opname == "DUP_TOP") or
                      (op.arg == "append" and
                       window[0].opname == "DUP_TOP" and
                       window[1].opname == "BUILD_LIST")):
                raise ValueError("direct attribute access %s: %s, %s:%d"
                                 % (op.opname, op.arg, code.co_filename, line))
        if op.opname in ("WITH_CLEANUP"):
            # Here we check if the LOAD_ATTR for __exit__ and
            # __enter__ were part of a 'with' statement by checking
            # for the 'WITH_CLEANUP' bytecode. If one is seen, we
            # clear the with_context variable and let it go. The
            # access was safe.
            with_context = (None, None)
        if op.opname in ("STORE_ATTR", "DEL_ATTR"):
            if not (window[0].opname == "CALL_FUNCTION" and
                    window[2].opname == "LOAD_GLOBAL" and
                    window[2].arg == "_write_"):
                # check that arg is appropriately wrapped
                for i, op in enumerate(window):
                    print i, op.opname, op.arg
                raise ValueError("unguard attribute set/del at %s:%d"
                                 % (code.co_filename, line))
        if op.opname.startswith("UNPACK"):
            # An UNPACK opcode extracts items from iterables, and that's
            # unsafe.  The restricted compiler doesn't remove UNPACK opcodes,
            # but rather *inserts* a call to _getiter_() before each, and
            # that's the pattern we need to see.
            if not (window[0].opname == "CALL_FUNCTION" and
                    window[1].opname == "ROT_TWO" and
                    window[2].opname == "LOAD_GLOBAL" and
                    window[2].arg == "_getiter_"):
                raise ValueError("unguarded unpack sequence at %s:%d" %
                                 (code.co_filename, line))

        # should check CALL_FUNCTION_{VAR,KW,VAR_KW} but that would
        # require a potentially unlimited history.  need to refactor
        # the "window" before I can do that.

        if op.opname == "LOAD_SUBSCR":
            raise ValueError("unguarded index of sequence at %s:%d" %
                             (code.co_filename, line))

        window = (op,) + window[:2]

    if not with_context == (None, None):
        # An access to __enter__ and __exit__ was performed but not as
        # part of a 'with' statement. This is not allowed.
        for op in with_context:
            if op is not None:
                if op.line is not None:
                    line = op.line
                raise ValueError("direct attribute access %s: %s, %s:%d"
                                 % (op.opname, op.arg, code.co_filename, line))


class Op(object):
    __slots__ = (
        "opname",   # string, name of the opcode
        "argcode",  # int, the number of the argument
        "arg",      # any, the object, name, or value of argcode
        "line",     # int, line number or None
        "target",   # boolean, is this op the target of a jump
        "pos",      # int, offset in the bytecode
    )

    def __init__(self, opcode, pos):
        self.opname = dis.opname[opcode]
        self.arg = None
        self.line = None
        self.target = False
        self.pos = pos


def disassemble(co, lasti=-1):
    code = co.co_code
    labels = dis.findlabels(code)
    linestarts = dict(findlinestarts(co))
    n = len(code)
    i = 0
    extended_arg = 0
    free = co.co_cellvars + co.co_freevars
    while i < n:
        op = ord(code[i])
        o = Op(op, i)
        i += 1
        if i in linestarts and i > 0:
            o.line = linestarts[i]
        if i in labels:
            o.target = True
        if op > dis.HAVE_ARGUMENT:
            arg = ord(code[i]) + ord(code[i + 1]) * 256 + extended_arg
            extended_arg = 0
            i += 2
            if op == dis.EXTENDED_ARG:
                extended_arg = arg << 16
            o.argcode = arg
            if op in dis.hasconst:
                o.arg = co.co_consts[arg]
            elif op in dis.hasname:
                o.arg = co.co_names[arg]
            elif op in dis.hasjrel:
                o.arg = i + arg
            elif op in dis.haslocal:
                o.arg = co.co_varnames[arg]
            elif op in dis.hascompare:
                o.arg = dis.cmp_op[arg]
            elif op in dis.hasfree:
                o.arg = free[arg]
        yield o


# findlinestarts is copied from Python 2.4's dis module.  The code
# didn't exist in 2.3, but it would be painful to code disassemble()
# without it.
def findlinestarts(code):
    """Find the offsets in a byte code which are start of lines in the source.

    Generate pairs (offset, lineno) as described in Python/compile.c.

    """
    byte_increments = [ord(c) for c in code.co_lnotab[0::2]]
    line_increments = [ord(c) for c in code.co_lnotab[1::2]]

    lastlineno = None
    lineno = code.co_firstlineno
    addr = 0
    for byte_incr, line_incr in zip(byte_increments, line_increments):
        if byte_incr:
            if lineno != lastlineno:
                yield (addr, lineno)
                lastlineno = lineno
            addr += byte_incr
        lineno += line_incr
    if lineno != lastlineno:
        yield (addr, lineno)
