import bytecode
import contextlib
import io
import opcode
import sys
import textwrap
import types
import unittest
from bytecode import Instr
from test_utils import TestCase


def LOAD_CONST(arg):
    return Instr(1, 'LOAD_CONST', arg)

def STORE_NAME(arg):
    return Instr(1, 'STORE_NAME', arg)

def NOP():
    return Instr(1, 'NOP')

def RETURN_VALUE():
    return Instr(1, 'RETURN_VALUE')

def disassemble(source, *, filename="<string>", function=False,
                remove_last_return_none=False, use_labels=True):
    source = textwrap.dedent(source).strip()
    code_obj = compile(source, filename, "exec")
    if function:
        sub_code = [const for const in code_obj.co_consts
                    if isinstance(const, types.CodeType)]
        if len(sub_code) != 1:
            raise ValueError("unable to find function code")
        code_obj = sub_code[0]

    code = bytecode.Code.disassemble(code_obj, use_labels=use_labels)
    if remove_last_return_none:
        # drop LOAD_CONST+RETURN_VALUE to only keep 2 instructions,
        # to make unit tests shorter
        block = code[-1]
        if not(block[-2].name == "LOAD_CONST"
               and block[-2].arg == code.consts.index(None)
               and block[-1].name == "RETURN_VALUE"):
            raise ValueError("unable to find implicit RETURN_VALUE <None>: %s"
                             % block[-2:])
        del block[-2:]
    return code


class InstrTests(TestCase):
    def test_constructor(self):
        # invalid line number
        with self.assertRaises(TypeError):
            Instr("x", "NOP")
        with self.assertRaises(ValueError):
            Instr(0, "NOP")

        # invalid name
        with self.assertRaises(TypeError):
            Instr(1, 1)
        with self.assertRaises(ValueError):
            Instr(1, "xxx")

        # invalid argument
        with self.assertRaises(TypeError):
            Instr(1, "LOAD_CONST", 1.0)
        with self.assertRaises(ValueError):
            Instr(1, "LOAD_CONST", -1)
        with self.assertRaises(ValueError):
            Instr(1, "LOAD_CONST", 2147483647+1)

        # test maximum argument
        instr = Instr(1, "LOAD_CONST", 2147483647)
        self.assertEqual(instr.arg, 2147483647)

    def test_attr(self):
        instr = Instr(5, "LOAD_CONST", 3)
        self.assertEqual(instr.lineno, 5)
        self.assertEqual(instr.name, 'LOAD_CONST')
        self.assertEqual(instr.arg, 3)
        self.assertEqual(instr.size, 3)
        self.assertEqual(instr.op, opcode.opmap['LOAD_CONST'])
        self.assertRaises(AttributeError, setattr, instr, 'lineno', 1)
        self.assertRaises(AttributeError, setattr, instr, 'name', 'LOAD_FAST')
        self.assertRaises(AttributeError, setattr, instr, 'arg', 2)

        instr = Instr(1, "ROT_TWO")
        self.assertEqual(instr.size, 1)
        self.assertIsNone(instr.arg)
        self.assertEqual(instr.op, opcode.opmap['ROT_TWO'])

    def test_extended_arg(self):
        instr = Instr(1, "LOAD_CONST", 0x1234abcd)
        self.assertEqual(instr.arg, 0x1234abcd)
        self.assertEqual(instr.assemble(), b'\x904\x12d\xcd\xab')

    def test_slots(self):
        instr = Instr(1, "NOP")
        with self.assertRaises(AttributeError):
            instr.myattr = 1

    def test_compare(self):
        instr = Instr(7, "LOAD_CONST", 3)
        self.assertEqual(instr, Instr(7, "LOAD_CONST", 3))

        self.assertNotEqual(instr, Instr(6, "LOAD_CONST", 3))
        self.assertNotEqual(instr, Instr(7, "LOAD_FAST", 3))
        self.assertNotEqual(instr, Instr(7, "LOAD_CONST", 4))

    def test_get_jump_target(self):
        jump_abs = Instr(1, "JUMP_ABSOLUTE", 3)
        self.assertEqual(jump_abs.get_jump_target(100), 3)

        jump_forward = Instr(1, "JUMP_FORWARD", 5)
        self.assertEqual(jump_forward.get_jump_target(10), 18)

        label = bytecode.Label()
        jump_label = Instr(1, "JUMP_FORWARD", label)
        with self.assertRaises(ValueError):
            jump_label.get_jump_target(10)

    def test_is_jump(self):
        jump = Instr(1, "JUMP_ABSOLUTE", 3)
        self.assertTrue(jump.is_jump())

        instr = Instr(1, "LOAD_FAST", 2)
        self.assertFalse(instr.is_jump())

    def test_is_cond_jump(self):
        jump = Instr(1, "POP_JUMP_IF_TRUE", 3)
        self.assertTrue(jump.is_cond_jump())

        instr = Instr(1, "LOAD_FAST", 2)
        self.assertFalse(instr.is_cond_jump())

    def test_assemble(self):
        instr = Instr(1, "NOP")
        self.assertEqual(instr.assemble(), b'\t')

        instr = Instr(1, "LOAD_CONST", 3)
        self.assertEqual(instr.assemble(), b'd\x03\x00')

    def test_disassemble(self):
        instr = Instr.disassemble(1, b'\td\x03\x00', 0)
        self.assertEqual(instr, Instr(1, "NOP"))

        instr = Instr.disassemble(1, b'\td\x03\x00', 1)
        self.assertEqual(instr, Instr(1, "LOAD_CONST", 3))

    def test_disassemble_extended_arg(self):
        code = b'\x904\x12d\xcd\xab'
        # without EXTENDED_ARG opcode
        instr = Instr.disassemble(1, code, 0)
        self.assertEqual(instr, Instr(1, "LOAD_CONST", 0x1234abcd))

        # with EXTENDED_ARG opcode
        instr1 = Instr.disassemble(1, code, 0,
                                            extended_arg_op=True)
        self.assertEqual(instr1, Instr(1, 'EXTENDED_ARG', 0x1234))

        instr2 = Instr.disassemble(1, code, instr1.size,
                                            extended_arg_op=True)
        self.assertEqual(instr2, Instr(1, 'LOAD_CONST', 0xabcd))


class CodeTests(TestCase):
    def test_attr(self):
        source = """
            first_line = 1

            def func(arg1, arg2, *, arg3):
                x = 1
                y = 2
                return arg1
        """
        code = disassemble(source, filename="hello.py", function=True)
        self.assertEqual(code.argcount, 2)
        self.assertEqual(code.consts, [None, 1, 2])
        self.assertEqual(code.filename, "hello.py")
        self.assertEqual(code.first_lineno, 3)
        self.assertEqual(code.kw_only_argcount, 1)
        self.assertEqual(code.name, "func")
        self.assertEqual(code.varnames, ["arg1", "arg2", "arg3", "x", "y"])
        self.assertEqual(code.names, [])
        self.assertEqual(code.freevars, [])
        self.assertEqual(code.cellvars, [])

        code = disassemble("a = 1; b = 2")
        self.assertEqual(code.names, ["a", "b"])

        # FIXME: test non-empty freevars
        # FIXME: test non-empty cellvars

    def test_constructor(self):
        code = bytecode.Code("name", "filename", 123)
        self.assertEqual(code.name, "name")
        self.assertEqual(code.filename, "filename")
        self.assertEqual(code.flags, 123)
        self.assertEqual(len(code), 1)
        self.assertEqual(code[0], [])

    def test_add_del_block(self):
        code = bytecode.Code("name", "filename", 0)
        code[0].append(LOAD_CONST(0))

        block = code.add_block()
        self.assertEqual(len(code), 2)
        self.assertIs(block, code[1])

        code[1].append(LOAD_CONST(2))
        self.assertEqual(code[0], [LOAD_CONST(0)])
        self.assertEqual(code[1], [LOAD_CONST(2)])

        del code[0]
        self.assertEqual(len(code), 1)
        self.assertEqual(code[0], [LOAD_CONST(2)])


class FunctionalTests(TestCase):
    def sample_code(self):
        code = disassemble('x = 1', remove_last_return_none=True)
        self.assertEqual(len(code), 1)
        self.assertListEqual(code[0], [LOAD_CONST(0), STORE_NAME(0)])
        return code

    def test_eq(self):
        # compare codes with multiple blocks and labels,
        # Code.__eq__() renumbers labels to get equal labels
        source = 'x = 1 if test else 2'
        code1 = disassemble(source)
        code2 = disassemble(source)
        self.assertEqual(code1, code2)

    def check_getitem(self, code):
        # check internal Code block indexes (index by index, index by label)
        for block_index, block in enumerate(code):
            self.assertIs(code[block_index], block)
            self.assertIs(code[block.label], block)

    def test_create_label_by_int_split(self):
        code = self.sample_code()
        code[0].append(NOP())

        label = code.create_label(0, 2)
        self.assertEqual(len(code), 2)
        self.assertListEqual(code[0], [LOAD_CONST(0), STORE_NAME(0)])
        self.assertListEqual(code[1], [NOP()])
        self.assertEqual(label, code[1].label)
        self.check_getitem(code)

        label3 = code.create_label(0, 1)
        self.assertEqual(len(code), 3)
        self.assertListEqual(code[0], [LOAD_CONST(0), ])
        self.assertListEqual(code[1], [STORE_NAME(0)])
        self.assertListEqual(code[2], [NOP()])
        self.assertEqual(label, code[2].label)
        self.check_getitem(code)

    def test_create_label_by_label_split(self):
        code = self.sample_code()
        block_index = code[0].label

        label = code.create_label(block_index, 1)
        self.assertEqual(len(code), 2)
        self.assertListEqual(code[0], [LOAD_CONST(0), ])
        self.assertListEqual(code[1], [STORE_NAME(0)])
        self.assertEqual(label, code[1].label)
        self.check_getitem(code)

    def test_create_label_dont_split(self):
        code = self.sample_code()

        label = code.create_label(0, 0)
        self.assertEqual(len(code), 1)
        self.assertListEqual(code[0], [LOAD_CONST(0), STORE_NAME(0)])
        self.assertEqual(label, code[0].label)

    def test_create_label_error(self):
        code = self.sample_code()

        with self.assertRaises(ValueError):
            # cannot create a label at the end of a block,
            # only between instructions
            code.create_label(0, 2)

    def test_assemble(self):
        # test resolution of jump labels
        code = disassemble("""
            if x:
                x = 2
            x = 3
        """)
        remove_jump_forward = sys.version_info >= (3, 5)
        if remove_jump_forward:
            blocks = [[Instr(1, 'LOAD_NAME', 0),
                       Instr(1, 'POP_JUMP_IF_FALSE', code[1].label),
                       Instr(2, 'LOAD_CONST', 0),
                       Instr(2, 'STORE_NAME', 0)],
                      [Instr(3, 'LOAD_CONST', 1),
                       Instr(3, 'STORE_NAME', 0),
                       Instr(3, 'LOAD_CONST', 2),
                       Instr(3, 'RETURN_VALUE')]]
            expected = (b'e\x00\x00'
                        b'r\x0c\x00'
                        b'd\x00\x00'
                        b'Z\x00\x00'
                        b'd\x01\x00'
                        b'Z\x00\x00'
                        b'd\x02\x00'
                        b'S')
        else:
            blocks = [[Instr(1, 'LOAD_NAME', 0),
                       Instr(1, 'POP_JUMP_IF_FALSE', code[1].label),
                       Instr(2, 'LOAD_CONST', 0),
                       Instr(2, 'STORE_NAME', 0),
                       Instr(2, 'JUMP_FORWARD', code[1].label)],
                      [Instr(3, 'LOAD_CONST', 1),
                       Instr(3, 'STORE_NAME', 0),
                       Instr(3, 'LOAD_CONST', 2),
                       Instr(3, 'RETURN_VALUE')]]
            expected = (b'e\x00\x00'
                        b'r\x0f\x00'
                        b'd\x00\x00'
                        b'Z\x00\x00'
                        b'n\x00\x00'
                        b'd\x01\x00'
                        b'Z\x00\x00'
                        b'd\x02\x00'
                        b'S')

        self.assertCodeEqual(code, *blocks)
        code2 = code.assemble()
        self.assertEqual(code2.co_code, expected)

    def test_disassemble(self):
        code = disassemble("""
            if test:
                x = 1
            else:
                x = 2
        """)
        self.assertEqual(len(code), 3)
        expected = [Instr(1, 'LOAD_NAME', 0),
                    Instr(1, 'POP_JUMP_IF_FALSE', code[1].label),
                    Instr(2, 'LOAD_CONST', 0),
                    Instr(2, 'STORE_NAME', 1),
                    Instr(2, 'JUMP_FORWARD', code[2].label)]
        self.assertListEqual(code[0], expected)

        expected = [Instr(4, 'LOAD_CONST', 1),
                    Instr(4, 'STORE_NAME', 1)]
        self.assertListEqual(code[1], expected)

        expected = [Instr(4, 'LOAD_CONST', 2),
                    Instr(4, 'RETURN_VALUE')]
        self.assertListEqual(code[2], expected)

    def test_disassemble_without_labels(self):
        code = disassemble("""
            if test:
                x = 1
            else:
                x = 2
        """, use_labels=False)
        self.assertEqual(len(code), 1)
        expected = [Instr(1, 'LOAD_NAME', 0),
                    Instr(1, 'POP_JUMP_IF_FALSE', 15),
                    Instr(2, 'LOAD_CONST', 0),
                    Instr(2, 'STORE_NAME', 1),
                    Instr(2, 'JUMP_FORWARD', 6),
                    Instr(4, 'LOAD_CONST', 1),
                    Instr(4, 'STORE_NAME', 1),
                    Instr(4, 'LOAD_CONST', 2),
                    Instr(4, 'RETURN_VALUE')]
        self.assertListEqual(code[0], expected)

    def test_lnotab(self):
        code = disassemble("""
            x = 1
            y = 2
            z = 3
        """, remove_last_return_none=True)
        self.assertEqual(len(code), 1)
        expected = [Instr(1, "LOAD_CONST", 0), Instr(1, "STORE_NAME", 0),
                    Instr(2, "LOAD_CONST", 1), Instr(2, "STORE_NAME", 1),
                    Instr(3, "LOAD_CONST", 2), Instr(3, "STORE_NAME", 2)]
        self.assertListEqual(code[0], expected)
        code_obj2 = code.assemble()

        self.assertEqual(code_obj2.co_lnotab, b'\x06\x01\x06\x01')

    def test_extended_arg_make_function(self):
        source = '''
            def foo(x: int, y: int):
                pass
        '''
        code = disassemble(source, remove_last_return_none=True)
        self.assertEqual(len(code), 1)
        expected = [Instr(1, "LOAD_NAME", 0),
                    Instr(1, "LOAD_NAME", 0),
                    Instr(1, "LOAD_CONST", 0),
                    Instr(1, "LOAD_CONST", 1),
                    Instr(1, "LOAD_CONST", 2),
                    Instr(1, "MAKE_FUNCTION", 3 << 16),
                    Instr(1, "STORE_NAME", 1)]
        self.assertListEqual(code[0], expected)
        self.assertListEqual(code.names, ['int', 'foo'])

    def test_dump_code(self):
        source = """
            def func(test):
                if test == 1:
                    return 1
                elif test == 2:
                    return 2
                return 3
        """
        expected = textwrap.dedent("""
            [Block #1]
              2  0    LOAD_FAST(0)
                 3    LOAD_CONST(1)
                 6    COMPARE_OP(2)
                 9    POP_JUMP_IF_FALSE(<block #1>)
              3 12    LOAD_CONST(1)
                15    RETURN_VALUE

            [Block #2]
              4 16    LOAD_FAST(0)
                19    LOAD_CONST(2)
                22    COMPARE_OP(2)
                25    POP_JUMP_IF_FALSE(<block #2>)
              5 28    LOAD_CONST(2)
                31    RETURN_VALUE

            [Block #3]
              6 32    LOAD_CONST(3)
                35    RETURN_VALUE

        """).lstrip()
        code = disassemble(source, function=True)
        with contextlib.redirect_stdout(io.StringIO()) as stderr:
            bytecode._dump_code(code)
            output = stderr.getvalue()

        self.assertEqual(output, expected)


class MiscTests(unittest.TestCase):
    def test_version(self):
        import setup
        self.assertEqual(bytecode.__version__, setup.VERSION)


if __name__ == "__main__":
    unittest.main()
