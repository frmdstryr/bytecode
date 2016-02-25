# alias to keep the 'bytecode' variable free
import bytecode as _bytecode
from bytecode.instr import Instr, Label, UNSET


class BaseBytecode:
    def __init__(self):
        self.argcount = 0
        self.kw_only_argcount = 0
        self._stacksize = 0
        self.flags = 0
        self.first_lineno = 1
        self.name = '<module>'
        self.filename = '<string>'
        self.docstring = UNSET

        # FIXME: move to ConcreteBytecode
        self.freevars = []
        self.cellvars = []

    def _copy_attr_from(self, bytecode):
        self.argcount = bytecode.argcount
        self.kw_only_argcount = bytecode.kw_only_argcount
        self._stacksize = bytecode._stacksize
        self.flags = bytecode.flags
        self.first_lineno = bytecode.first_lineno
        self.name = bytecode.name
        self.filename = bytecode.filename
        self.docstring = bytecode.docstring
        self.freevars = list(bytecode.freevars)
        self.cellvars = list(bytecode.cellvars)

    def __eq__(self, other):
        if type(self) != type(other):
            return False

        if self.argcount != other.argcount:
            return False
        if self.kw_only_argcount != other.kw_only_argcount:
            return False
        if self._stacksize != other._stacksize:
            return False
        if self.flags != other.flags:
            return False
        if self.first_lineno != other.first_lineno:
            return False
        if self.filename != other.filename:
            return False
        if self.name != other.name:
            return False
        if self.docstring != other.docstring:
            return False
        if self.freevars != other.freevars:
            return False
        if self.cellvars != other.cellvars:
            return False

        return True


class _InstrList(list):
    def _flat(self):
        instructions = []
        labels = {}
        jumps = []
        offset = 0

        for index, instr in enumerate(self):
            if isinstance(instr, Label):
                labels[instr] = offset
            else:
                offset += 1
                if isinstance(instr.arg, Label):
                    # copy the instruction to be able to modify
                    # its argument above
                    instr = Instr(instr.lineno, instr.name, instr.arg)
                    jumps.append(instr)
                instructions.append(instr)

        for instr in jumps:
            instr.arg = labels[instr.arg]

        return instructions

    def __eq__(self, other):
        if not isinstance(other, _InstrList):
            other = _InstrList(other)

        return (self._flat() == other._flat())


class Bytecode(_InstrList, BaseBytecode):
    def __init__(self):
        BaseBytecode.__init__(self)
        self.argnames = []

    @staticmethod
    def from_code(code):
        return _bytecode.ConcreteBytecode.from_code(code).to_bytecode()

    def to_code(self):
        return self.to_concrete_bytecode().to_code()

    def to_concrete_bytecode(self):
        return _bytecode._ConvertCodeToConcrete(self).to_concrete_bytecode()

    def to_bytecode(self):
        return self

    def to_bytecode_blocks(self):
        # label => instruction index
        index_to_label = {}
        label_to_index = {}
        jumps = []
        for index, instr in enumerate(self):
            if isinstance(instr, Label):
                label = instr
                label_to_index[label] = index
                index_to_label[index] = label
            elif isinstance(instr.arg, Label):
                jumps.append(instr.arg)

        block_starts = {}
        for label in jumps:
            index = label_to_index[label]
            block_starts[index] = label

        bytecode = _bytecode.BytecodeBlocks()
        bytecode._copy_attr_from(self)
        bytecode.argnames = list(self.argnames)

        # copy instructions, convert labels to block labels
        block = bytecode[0]
        labels = {}
        jumps = []
        for index, instr in enumerate(self):
            if index != 0 and index in block_starts:
                old_label = block_starts[index]
                block = bytecode.add_block()
                labels[old_label] = block.label
                # FIXME: remap labels

            if isinstance(instr, Label):
                pass
            else:
                instr = Instr(instr.lineno, instr.name, instr.arg)
                if isinstance(instr.arg, Label):
                    jumps.append(instr)
                block.append(instr)

        for instr in jumps:
            label = instr.arg
            instr.arg = labels[label]

        return bytecode