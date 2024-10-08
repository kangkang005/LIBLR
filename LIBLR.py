#! /usr/bin/env python
# -*- coding: utf-8 -*-
#  vim: set ts=4 sw=4 tw=0 et :
#======================================================================
#
# LIBLR.py - Parser Generator with LR(1) and LALR
#
# History of this file:
#
#   2023.01.20  skywind  grammar definition
#   2023.01.21  skywind  grammar analayzer
#   2023.01.22  skywind  basic tokenizer
#   2023.01.23  skywind  grammar loader
#   2023.01.24  skywind  LR(1) generator
#   2023.01.25  skywind  LALR generator
#   2023.01.25  skywind  Lexer & PDAInput
#   2023.01.26  skywind  PDA
#   2023.01.26  skywind  conflict solver
#   2023.01.27  skywind  better error checking
#   2023.02.22  skywind  new print() method for Node class
#
#======================================================================
from __future__ import unicode_literals, print_function
import sys
import os
import time
import json
import copy
import re
import collections
import pprint

from enum import Enum, IntEnum

from typing import Generator


#----------------------------------------------------------------------
# exports
#----------------------------------------------------------------------
__all__ = ['GrammarError', 'Symbol', 'Vector', 'Production', 'Grammar',
           'Token', 'Parser', 'LRTable', 'Action', 'ActionName', 'Node',
           'create_parser', 'create_parser_from_file', 'load_from_string',
           'LR1Analyzer', 'GrammarAnalyzer']


#----------------------------------------------------------------------
# logs
#----------------------------------------------------------------------
LOG_ERROR = lambda *args: print('error:', *args)
LOG_WARNING = lambda *args: print('warning:', *args)
LOG_INFO = lambda *args: print('info:', *args)
LOG_DEBUG = lambda *args: print('debug:', *args)
LOG_VERBOSE = lambda *args: print('debug:', *args)

# ignore log levels
LOG_VERBOSE = lambda *args: 0
LOG_DEBUG = lambda *args: 0


#----------------------------------------------------------------------
# GrammarError
#----------------------------------------------------------------------
class GrammarError (Exception):
    pass


#----------------------------------------------------------------------
# 符号类：包括终结符和非终结符，term 代表是否为终结符，
# 空的话用空字符串表示
#----------------------------------------------------------------------
class Symbol (object):

    def __init__ (self, name, terminal = False):
        self.name = name
        self.term = terminal

    # 转为可打印字符串
    def __str__ (self):
        if not self.name:
            return "''"
        return self.name

    # 根据不同的类型判断是否相等
    def __eq__ (self, symbol):
        if isinstance(symbol, str):
            return (self.name == symbol)
        elif symbol is None:
            return (self is None)
        elif not isinstance(symbol, type(self)):
            raise TypeError('Symbol cannot be compared to a %s'%type(symbol))
        return (self.name == symbol.name)

    def __ne__ (self, symbol):
        return (not (self == symbol))

    # >=
    def __ge__ (self, symbol):
        return (self.name >= symbol.name)

    # > 
    def __gt__ (self, symbol):
        return (self.name > symbol.name)

    # <=
    def __le__ (self, symbol):
        return (self.name <= symbol.name)

    # < 
    def __lt__ (self, symbol):
        return (self.name < symbol.name)

    def __repr__ (self):
        if not self.term:
            return '%s(%r)'%(type(self).__name__, self.name)
        return '%s(%r, %r)'%(type(self).__name__, self.name, self.term)

    # 求哈希，有这个函数可以将 Symbol 放到容器里当 key
    def __hash__ (self):
        return hash(self.name)

    # 拷贝
    def __copy__ (self):
        obj = Symbol(self.name, self.term)
        if hasattr(self, 'value'):
            obj.value = self.value
        if hasattr(self, 'token'):
            obj.token = self.token
        return obj

    # 深度拷贝
    def __deepcopy__ (self):
        obj = Symbol(self.name, self.term)
        if hasattr(self, 'value'):
            obj.value = copy.deepcopy(self.value)
        if hasattr(self, 'token'):
            obj.token = copy.deepcopy(self.token)
        return obj

    # 判断是否是字符串字面量, 被引号包围的字符串为字面量
    def _is_literal (self):
        if len(self.name) < 2:
            return False
        mark = self.name[0]
        if mark not in ('"', "'"):
            return False
        # "string" or 'string'
        if self.name[-1] == mark:
            return True
        return False

    # 判断是否是空/epsilon
    @property
    def is_epsilon (self):
        if self.term:
            return False
        elif self.name == '':
            return True
        if self.name in ('%empty', '%e', '%epsilon', '\u03b5', '<empty>'):
            return True
        return False

    # 判断是否是字符串字面量
    @property
    def is_literal (self):
        return self._is_literal()


#----------------------------------------------------------------------
# 从字符串或者 tuple 创建一个 Symbol
#----------------------------------------------------------------------
def load_symbol (source):
    # load_symbol(Symbol("$", True))
    if isinstance(source, Symbol):
        return source
    # load_symbol("$")
    elif isinstance(source, str):
        sym = Symbol(source)
        # 字符串字面量视为终结符
        if sym.is_literal:
            sym.term = True
            # 只有引号("" or '')，视为非终结符
            if len(sym.name) == 2 and sym.name[0] == sym.name[1]:
                sym.term = False
                sym.name = ''
            try: sym.value = eval(sym.name)
            except: pass
        elif source == '$':
            sym.term = True
        elif source == '#':
            sym.term = True
        return sym
    # load_symbol(("$"))
    # load_symbol(("$", True))
    elif isinstance(source, list) or isinstance(source, tuple):
        assert len(source) > 0
        if len(source) == 0:
            raise ValueError('bad symbol: %r'%source)
        elif len(source) == 1:
            return Symbol(source[0])
        elif len(source) == 2:
            return Symbol(source[0], source[1])
        s = Symbol(source[0], source[1])
        s.value = source[2]
        return s
    raise ValueError('bad symbol: %r'%source)


#----------------------------------------------------------------------
# 符号矢量：符号列表
#----------------------------------------------------------------------
class Vector (object):

    def __init__ (self, vector:list):
        # 产生式的右边
        self.m = tuple(self.__load_vector(vector))
        self.__hash = None

    def __load_vector (self, vector):
        epsilon = True
        output = []
        p = [ load_symbol(n) for n in vector ]
        # 从符号列表中删除最左边的 epsilon
        for symbol in p:
            if not symbol.is_epsilon:
                epsilon = False
                break
        if not epsilon:
            for n in p:
                if not n.is_epsilon:
                    output.append(n)
        return output

    def __len__ (self):
        return len(self.m)

    def __getitem__ (self, index):
        return self.m[index]

    def __contains__ (self, key):
        if isinstance(key, int):
            return (key >= 0 and key < len(self.m))
        for n in self.m:
            if n == key:
                return True
        return False

    def __hash__ (self):
        if self.__hash is None:
            h = tuple([n.name for n in self.m])
            self.__hash = hash(h)
        return self.__hash

    def __iter__ (self):
        return self.m.__iter__()

    def __repr__ (self):
        return '%s(%r)'%(type(self).__name__, self.m)

    def __str__ (self):
        body = [ str(n) for n in self.m ]
        return ' '.join(body)

    def __eq__ (self, p):
        assert isinstance(p, Vector)
        if hash(self) != hash(p):
            return False
        return (self.m == p.m)

    def __ne__ (self, p):
        return (not (self == p))

    def __ge__ (self, p):
        return (self.m >= p.m)

    def __gt__ (self, p):
        return (self.m > p.m)

    def __le__ (self, p):
        return (self.m <= p.m)

    def __lt__ (self, p):
        return (self.m < p.m)

    def __copy__ (self):
        obj = Vector(self.m)
        obj.__hash = self.__hash
        return obj

    def __deepcopy__ (self):
        p = [ n.__deepcopy__() for n in self.m ]
        obj = Vector(p)
        obj.__hash = self.__hash
        return obj

    def search (self, symbol, stop = -1):
        if stop < 0:
            return self.m.index(symbol)
        return self.m.index(symbol, stop)

    @property
    def is_empty (self):
        return (len(self.m) == 0)

    # 计算最左边的终结符
    def leftmost_terminal (self):
        for n in self.m:
            if n.term:
                return n
        return None

    # 计算最右边的终结符
    def rightmost_terminal (self):
        index = len(self.m) - 1
        while index >= 0:
            symbol = self.m[index]
            if symbol.term:
                return symbol
            index -= 1
        return None


#----------------------------------------------------------------------
# 产生式/生成式：由 head -> body 组成，head 是 symbol，
# body 是一个 Vector，即 symbol 组成的序列
# index 是产生式的序列号
#----------------------------------------------------------------------
class Production (object):

    def __init__ (self, head, body:list, index = -1):
        self.head = load_symbol(head)
        self.body = Vector(body)
        self.__hash = None
        self.index = index
        self.is_epsilon = None
        self.has_epsilon = None
        # 优先级
        self.precedence = None
        # 语义动作
        self.action: dict[int, tuple[str, int]] = None  # {token pos: (token value, token pos)}
        # such as: {1: [('{get}', 1)]}

    def __len__ (self):
        return len(self.body)

    def __getitem__ (self, index):
        return self.body[index]

    def __contains__ (self, key):
        return (key in self.body)

    def __hash__ (self):
        if self.__hash is None:
            # self.head 和 self.body 是对象，先将对象转化成哈希值，再放入到 tuple 容器
            # self.head 和 self.body 指向的对象必须含有 __hash__ 方法
            h1 = hash(self.head)
            h2 = hash(self.body)
            self.__hash = hash((h1, h2))
        return self.__hash

    def __iter__ (self):
        return self.body.__iter__()

    def __repr__ (self):
        return '%s(%r, %r)'%(type(self).__name__, self.head, self.body)

    def __str__ (self):
        body = [ str(n) for n in self.body ]
        return '%s: %s ;'%(self.head, ' '.join(body))

    # 利用对象的哈希值进行比较
    def __eq__ (self, p):
        assert isinstance(p, Production)
        if hash(self) != hash(p):
            return False
        if self.head != p.head:
            return False
        return (self.body == p.body)

    def __ne__ (self, p):
        return not (self == p)

    def __ge__ (self, p):
        if self.head > p.head: 
            return True
        elif self.head < p.head:
            return False
        return (self.body >= p.body)

    def __gt__ (self, p):
        if self.head > p.head:
            return True
        elif self.head < p.head:
            return False
        return (self.body > p.body)

    def __lt__ (self, p):
        return (not (self >= p))

    def __le__ (self, p):
        return (not (self > p))

    def __copy__ (self):
        obj = Production(self.head, self.body)
        obj.index = self.index
        obj.precedence = self.precedence
        obj.is_epsilon = self.is_epsilon
        obj.has_epsilon = self.has_epsilon
        obj.__hash = self.__hash
        obj.action = self.action
        return obj

    def __deepcopy__ (self):
        p = self.body.__deepcopy__()
        obj = Production(self.head.__deepcopy__(), p)
        obj.index = self.index
        obj.precedence = self.precedence
        obj.is_epsilon = self.is_epsilon
        obj.has_epsilon = self.has_epsilon
        obj.__hash = self.__hash
        if self.action:
            obj.action = copy.deepcopy(self.action)
        return obj

    def search (self, symbol, stop = -1):
        return self.body.search(symbol, stop)

    @property
    def is_empty (self):
        return (len(self.body) == 0)

    # 计算最右边的终结符
    def rightmost_terminal (self):
        return self.body.rightmost_terminal()

    # 最左侧的终结符
    def leftmost_terminal (self):
        return self.body.leftmost_terminal()

    # 计算是否直接左递归, 判断 head 是否等于产生式右边的第一个符号
    @property
    def is_left_recursion (self):
        if len(self.body) == 0:
            return False
        return (self.head == self.body[0])

    # 计算是否直接右递归, 判断 head 是否等于产生式右边的最后一个符号
    @property
    def is_right_recursion (self):
        if len(self.body) == 0:
            return False
        return (self.head == self.body[-1])

    def __action_to_string (self, m):
        if isinstance(m, str):
            return m
        assert isinstance(m, tuple)
        name:str = m[0]
        stack = m[1]
        if name.startswith('{') and name.endswith('}'):
            return '{%s/%d}'%(name[1:-1], stack)
        return '%s/%d'%(name, stack)

    # 返回包含动作的身体部分
    # prec 优先级
    def stringify (self, head = True, body = True, action = False, prec = False):
        text = ''
        if head:
            text += str(self.head) + ': '
        act = getattr(self, 'action', {})
        if body:
            for i, n in enumerate(self.body):
                if action and act and (i in act):
                    for m in act[i]:
                        text += '%s '%self.__action_to_string(m)
                text += n.name + ' '
            i = len(self.body)
            if action and act and (i in act):
                for m in act[i]:
                    text += '%s '%self.__action_to_string(m)
        if prec:
            text += ' <%s>'%(self.precedence, )
        return text.strip('\r\n\t ')



#----------------------------------------------------------------------
# 语法类，一个语法 G 由终结符，非终结符和产生式组成
#----------------------------------------------------------------------
class Grammar (object):

    """example
    E: E '+' T | T
    E: E '-' T
    @ignore [ \r\n\t]*
    @match NUMBER [+-]?\d+(\.\d*)?

    self.production = [
        Production(Symbol('E'), Vector((Symbol('E'), Symbol("'+'", True), Symbol('T')))),
        Production(Symbol('E'), Vector((Symbol('E'), Symbol("'-'", True), Symbol('T')))),
        Production(Symbol('E'), Vector((Symbol('T'),)))
    ]
    self.symbol = {
        "E"  : Symbol("E"),
        "'+'": Symbol("'+'", True),
        "T"  : Symbol("T"),
        "'-'": Symbol("'-'", True),
    }
    self.terminal = {
        "'+'": Symbol("'+'", True),
        "'-'": Symbol("'-'", True)
    }
    self.rule = {
        'E': [
            Production(Symbol('E'), Vector((Symbol('E'), Symbol("'+'", True), Symbol('T')))),
            Production(Symbol('E'), Vector((Symbol('E'), Symbol("'-'", True), Symbol('T')))),
            Production(Symbol('E'), Vector((Symbol('T'),)))
        ]
    }
    self.scanner = {
        ('ignore', '[ \\r\\n\\t]*'),
        ('match', 'NUMBER', '[+-]?\\d+(\\.\\d*)?'),
    }
    """
    def __init__ (self):
        self.production = []
        self.symbol = {}            # symbol name str -> Symbol map
        self.terminal = {}          # symbol name str -> Symbol map
        self.rule = {}              # head name(left production) str -> Production list
        self.precedence = {}        # str -> prec
        self.assoc = {}             # str -> one of (None, 'left', 'right')
        self._anchor = {}           # str -> (filename, linenum)
        self._dirty = False         # be modified if True
        self.scanner = []           # scanner rules
        self.start = None           # Symbol | None

    def reset (self):
        self.production.clear()
        self.symbol.clear()
        self.terminal.clear()
        self.nonterminal.clear()
        self.rule.clear()
        self._anchor.clear()
        self.scanner.clear()
        self.start = None
        return 0

    def _symbol_name (self, symbol):
        if isinstance(symbol, Symbol):
            return symbol.name
        elif isinstance(symbol, str):
            return symbol
        raise TypeError('bad symbol: %r'%symbol)

    def __len__ (self):
        return len(self.production)

    def __getitem__ (self, index):
        return self.production[index]

    def __iter__ (self):
        return self.production.__iter__()

    def __contains__ (self, key):
        if isinstance(key, int):
            return (key >= 0 and key < len(self.production))
        elif isinstance(key, Production):
            for p in self.production:
                # 利用对象的哈希值进行比较
                if p == key:
                    return True
        elif isinstance(key, Symbol):
            return (key.name in self.symbol)
        elif isinstance(key, str):
            return (key in self.symbol)
        return False

    def __copy__ (self):
        obj = Grammar()
        for p in self.production:
            obj.push_production(p.__copy__())
        for t in self.terminal:
            obj.push_token(t)
        for p in self.precedence:
            c = self.precedence[p]
            obj.push_precedence(p, c[0], c[1])
        obj.srcinfo = self.srcinfo.__copy__()
        obj.update()
        if self.start:
            obj.start = obj.symbol[self.start.name]
        return obj

    def __deepcopy__ (self, memo):
        obj = Grammar()
        for p in self.production:
            obj.push_production(p.__deepcopy__(memo))
        for t in self.terminal:
            obj.push_token(t)
        for p in self.precedence:
            c = self.precedence[p]
            obj.push_precedence(p, c[0], c[1])
        obj.srcinfo = self.srcinfo.__deepcopy__(memo)
        obj.update()
        if self.start:
            obj.start = obj.symbol[self.start.name]
        return obj

    def insert (self, index, production):
        self.production.insert(index, production)
        self._dirty = True      # be modified

    def search (self, p, stop = -1):
        if stop < 0:
            return self.production.index(p)
        return self.production.index(p, stop)

    def remove (self, index):
        if isinstance(index, int):
            self.production.pop(index)
        else:
            index = self.search(index)
            self.production.pop(index)
        self._dirty = True

    def pop (self, index = -1):
        self.production.pop(index)
        self._dirty = True

    def append (self, production):
        index = len(self.production)
        self.production.append(production)
        production.index = index
        self._dirty = True

    def replace (self, index, source):
        if isinstance(source, Production):
            self.production[index] = source
        # 将其中一个产生式替换成多个产生式
        elif isinstance(source, list) or isinstance(source, tuple):
            for n in source:
                assert isinstance(n, Production)
                self.production.insert(index + 1, n)
            self.production.pop(index)
        self._dirty = True

    def update (self):
        self.symbol.clear()
        self.rule.clear()
        for i, p in enumerate(self.production):
            # p: production
            p.index = i
            head = p.head
            if head.name not in self.symbol:
                self.symbol[head.name] = head
            for n in p.body:
                # n: symbol
                if n.name not in self.symbol:
                    self.symbol[n.name] = n
            self.rule.setdefault(head.name, []).append(p)
        for n in self.terminal:
            s = self.terminal[n]
            if not s.term:
                s.term = True
        for n in self.symbol:
            s = self.symbol[n]
            s.term = (n in self.terminal)
            if not s.term:
                if s.name not in self.rule:
                    self.rule[s.name] = []
        for p in self.production:
            p.head.term = (p.head.name in self.terminal)
            for n in p.body:
                n.term = (n.name in self.terminal)
        for p in self.production:
            if p.precedence is None:
                rightmost = p.rightmost_terminal()
                if rightmost and (rightmost in self.precedence):
                    p.precedence = rightmost.name
        self._dirty = False
        return 0

    # declare terminal
    def push_token (self, token):
        name = self._symbol_name(token)
        if token not in self.terminal:
            t = load_symbol(token)
            t.term = True
            self.terminal[name] = t
        self._dirty = True
        return 0

    # push precedence
    def push_precedence (self, symbol, prec, assoc):
        name = self._symbol_name(symbol)
        if prec == 'precedence':
            prec = 'left'
        self.precedence[name] = prec
        self.assoc[name] = assoc

    # push scanner (aka. lexer) rules
    def push_scanner (self, obj):
        self.scanner.append(obj)
        return 0

    # create new symbol according to self.terminal
    def create_symbol (self, name):
        cc = load_symbol(name)
        if name != '':
            if name in self.terminal:
                cc.term = True
        return cc

    # 新增产生式 S' -> S, 构成增广文法(augmented grammar)
    # augment
    def augment (self):
        if not self.start:
            raise GrammarError('no start point')
        if 'S^' in self.symbol:
            raise GrammarError('already augmented')
        head = 'S^'
        p = Production(head, [self.start])
        self.insert(0, p)
        self.start = p.head
        self.update()
        return 0

    def __anchor_key (self, obj):
        if isinstance(obj, str):
            return obj
        elif isinstance(obj, Symbol):
            return str(obj)
        elif isinstance(obj, int):
            return '^INT/' + str(obj)
        elif isinstance(obj, Vector):
            return '^VEC/' + str(obj)
        elif isinstance(obj, Production):
            return '^PROD/' + str(obj)
        return str(obj)

    # use to print symbol message
    # anchor: source file info -> (filename, line_num)
    def anchor_set (self, obj, filename, line_num):
        self._anchor[self.__anchor_key(obj)] = (filename, line_num)
        return 0

    def anchor_get (self, obj):
        key = self.__anchor_key(obj)
        if key not in self._anchor:
            return (None, None)
        return self._anchor[key]

    def anchor_has (self, obj):
        key = self.__anchor_key(obj)
        return (key in self._anchor)

    def print (self, mode = 0, action = False, prec = False):
        text = ""
        if mode == 0:
            for i, n in enumerate(self.production):
                t = '(%d) %s'%(i+1, n.stringify(True, True, action, prec))
                text += t+'\n'
                print(t)
            return text
        else:
            keys = list(self.rule.keys())
            for key in keys:
                head = str(key) + ': '
                padding = ' ' * (len(head) - 2)
                for i, p in enumerate(self.rule[key]):
                    if i == 0:
                        print(head, end = '')
                    else:
                        print(padding + '| ', end = '')
                    print(p.stringify(False, True, action, prec), end = ' ')
                    if len(self.rule[key]) > 1:
                        print('')
                if len(self.rule[key]) > 1:
                    print(padding + ';')
                else:
                    print(';')
        return 0

    def __str__ (self):
        text = []
        for i, n in enumerate(self.production):
            t = '(%d) %s'%(i, str(n))
            text.append(t)
        return '\n'.join(text)




#----------------------------------------------------------------------
# Token: (name, value, line, column)
# name represents token type, since "type" is a reserved word in 
# python, choose "name" instead
#----------------------------------------------------------------------
class Token (object):

    def __init__ (self, name, value, line = 0, column = 0):
        self.name = name
        self.value = value
        self.line = line
        self.column = column

    def __str__ (self):
        if self.line is None:
            return '(%s, %s)'%(self.name, self.value)
        t = (self.name, self.value, self.line, self.column)
        return '(%s, %s, %s, %s)'%t

    def __repr__ (self):
        n = type(self).__name__
        if self.line is None:
            return '%s(%r, %r)'%(n, self.name, self.value)
        t = (n, self.name, self.value, self.line, self.column)
        return '%s(%r, %r, %r, %r)'%t

    def __copy__ (self):
        return Token(self.name, self.value, self.line, self.column)


#----------------------------------------------------------------------
# tokenize
#----------------------------------------------------------------------
def _tokenize(code, specs, eof = None):
    patterns = []
    definition = {}
    extended = {}
    if not specs:
        return None
    for index in range(len(specs)):
        spec = specs[index]
        name, pattern = spec[:2]
        # pn: pattern name
        pn = 'PATTERN%d'%index
        definition[pn] = name       # pattern name -> call | None | token name
        if len(spec) >= 3:
            extended[pn] = spec[2]
        patterns.append((pn, pattern))
    tok_regex = '|'.join('(?P<%s>%s)' % pair for pair in patterns)
    # print(tok_regex)
    # 每行的起始位置, 索引号代表行号
    line_starts = []
    pos = 0
    index = 0
    while 1:
        line_starts.append(pos)
        pos = code.find('\n', pos)
        if pos < 0:
            break
        pos += 1
    line_num = 0
    for mo in re.finditer(tok_regex, code):
        # group variable name: PATTERN0, PATTERN1 ...
        kind = mo.lastgroup
        value = mo.group()
        start = mo.start()
        while line_num < len(line_starts) - 1:
            if line_starts[line_num + 1] > start:
                break
            line_num += 1
        line_start = line_starts[line_num]
        name = definition[kind]
        if name is None:
            continue
        if callable(name):
            if kind not in extended:
                obj = name(value)
            else:
                obj = name(value, extended[kind])
            name = None
            if isinstance(obj, list) or isinstance(obj, tuple):
                if len(obj) > 0: 
                    name = obj[0]
                if len(obj) > 1:
                    value = obj[1]
            else:
                name = obj
        # "line_num" starts at 0
        # (<token name>, <token value>, <line number>, <column>)
        yield (name, value, line_num + 1, start - line_start + 1)
    if eof is not None:
        line_start = line_starts[-1]
        endpos = len(code)
        yield (eof, '', len(line_starts), endpos - line_start + 1)
    return 0


#----------------------------------------------------------------------
# Tokenize
#----------------------------------------------------------------------
def tokenize(code, rules, eof = None):
    for info in _tokenize(code, rules, eof):
        yield Token(info[0], info[1], info[2], info[3])
    return 0


#----------------------------------------------------------------------
# validate pattern
#----------------------------------------------------------------------
def validate_pattern(pattern):
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


#----------------------------------------------------------------------
# replace '{name}' in a pattern with the text in "macros[name]"
#----------------------------------------------------------------------
def regex_expand(macros, pattern, guarded = True):
    output = []
    pos = 0
    size = len(pattern)
    while pos < size:
        ch = pattern[pos]
        if ch == '\\':
            output.append(pattern[pos:pos + 2])
            pos += 2
            continue
        elif ch != '{':
            output.append(ch)
            pos += 1
            continue
        p2 = pattern.find('}', pos)
        if p2 < 0:
            output.append(ch)
            pos += 1
            continue
        p3 = p2 + 1
        name = pattern[pos + 1:p2].strip('\r\n\t ')
        if name == '':
            output.append(pattern[pos:p3])
            pos = p3
            continue
        if name[0].isdigit():
            output.append(pattern[pos:p3])
            pos = p3
            continue
        if ('<' in name) or ('>' in name):
            raise ValueError('invalid pattern name "%s"'%name)
        if name not in macros:
            raise ValueError('{%s} is undefined'%name)
        if guarded:
            output.append('(?:' + macros[name] + ')')
        else:
            output.append(macros[name])
        pos = p3
    return ''.join(output)


#----------------------------------------------------------------------
# build regex info
#----------------------------------------------------------------------
def regex_build(code, macros = None, capture = True):
    defined = {}
    if macros is not None:
        for k, v in macros.items():
            defined[k] = v
    line_num = 0
    for line in code.split('\n'):
        line_num += 1
        line = line.strip('\r\n\t ')
        if (not line) or line.startswith('#'):
            continue
        pos = line.find('=')
        if pos < 0:
            raise ValueError('%d: not a valid rule'%line_num)
        head = line[:pos].strip('\r\n\t ')
        body = line[pos + 1:].strip('\r\n\t ')
        if (not head):
            raise ValueError('%d: empty rule name'%line_num)
        elif head[0].isdigit():
            raise ValueError('%d: invalid rule name "%s"'%(line_num, head))
        elif ('<' in head) or ('>' in head):
            raise ValueError('%d: invalid rule name "%s"'%(line_num, head))
        try:
            pattern = regex_expand(defined, body, guarded = not capture)
        except ValueError as e:
            raise ValueError('%d: %s'%(line_num, str(e)))
        try:
            re.compile(pattern)
        except re.error:
            raise ValueError('%d: invalid pattern "%s"'%(line_num, pattern))
        if not capture:
            defined[head] = pattern
        else:
            defined[head] = '(?P<%s>%s)'%(head, pattern)
    return defined


#----------------------------------------------------------------------
# predefined patterns
#----------------------------------------------------------------------
PATTERN_WHITESPACE = r'[ \t\r\n]+'
PATTERN_COMMENT1 = r'[#].*'
PATTERN_COMMENT2 = r'\/\/.*'
PATTERN_COMMENT3 = r'\/\*([^*]|[\r\n]|(\*+([^*/]|[\r\n])))*\*+\/'
PATTERN_MISMATCH = r'.'
PATTERN_NAME = r'\w+'
PATTERN_GNAME = r'\w(?:\w|\@)*[\']*'
PATTERN_STRING1 = r"'(?:\\.|[^'\\])*'"
PATTERN_STRING2 = r'"(?:\\.|[^"\\])*"'
PATTERN_NUMBER = r'\d+(\.\d*)?'
PATTERN_CINTEGER = r'(0x)?\d+[uUlLbB]*'
PATTERN_REPLACE = r'(?<!\\)\{\s*[a-zA-Z_]\w*\s*\}'
# PATTERN_CFLOAT = r'\d*(\.\d*)?f*'   # bad pattern, don't use
PATTERN_EPSILON = '\u03b5'
PATTERN_GMACRO = r'[%]\s*\w+'
PATTERN_OPERATOR = r'[\+\-\*\/\?\%]'


#----------------------------------------------------------------------
# predefined lexer rules
#----------------------------------------------------------------------
lex_rules = r'''
    O = [0-7]
    D = [0-9]
    NZ = [1-9]
    L = [a-zA-Z_]
    A = [a-zA-Z_0-9]
    H = [a-fA-F0-9]
    HP = (0[xX])
    E = ([Ee][+-]?{D}+)
    P = ([Pp][+-]?{D}+)
    FS = (f|F|l|L)
    IS = (((u|U)(l|L|ll|LL)?)|((l|L|ll|LL)(u|U)?))
    CP = (u|U|L)
    SP = (u8|u|U|L)

    WHITESPACE = \s+
    WS = \s+
    EOL = [\n]+
    WSEOL = {WS}|{EOL}
    COMMENT1 = [#].*
    COMMENT2 = \/\/.*
    COMMENT3 = \/\*([^*]|[\r\n]|(\*+([^*/]|[\r\n])))*\*+\/
    COMMENT = {COMMENT1}|{COMMENT2}|{COMMENT3}
    NAME = {L}{A}*
    STRING1 = '(?:\\.|[^'\\])*'
    STRING2 = "(?:\\.|[^"\\])*"
    STRING = {STRING1}|{STRING2}
    DIGIT = [0-9]
    DIGITS = {DIGIT}+
    HEX = {HP}{H}+
    DEC = {NZ}{D}*
    INTEGER = ({HEX}|{DEC})(({IS}|{CP})?)
    FLOAT = {DIGITS}((\.{DIGITS})?)({E}?)({FS}?)
    NUMBER = {INTEGER}|{FLOAT}
'''


#----------------------------------------------------------------------
# build
#----------------------------------------------------------------------
PATTERN = regex_build(lex_rules, capture = False)


#----------------------------------------------------------------------
# internal utils
#----------------------------------------------------------------------
class internal (object):

    @staticmethod
    def echo_error(text, fn = None, line_num = 0, col = None):
        # fn: file name
        name = (not fn) and '<buffer>' or fn
        if not fn:
            # print text
            t = 'error: %s'%(text, )
        elif (not col) or (col < 0):
            # print text line_num
            t = 'error:%s:%d: %s'%(name, line_num, text)
        else:
            # print text line_num col
            t = 'error:%s:%d:%d: %s'%(name, line_num, col, text) 
        LOG_ERROR(t)
        return 0

    @staticmethod
    def echo_warning(text, fn = None, line_num = 0, col = None):
        name = (not fn) and '<buffer>' or fn
        if not fn:
            t = 'warning: %s'%(text, )
        elif (not col) or (col < 0):
            t = 'warning:%s:%d: %s'%(name, line_num, text)
        else:
            t = 'warning:%s:%d:%d: %s'%(name, line_num, col, text) 
        LOG_WARNING(t)
        return 0

    @staticmethod
    def log_info(*args):
        LOG_INFO(*args)
        return 0

    @staticmethod
    def log_debug(*args):
        LOG_DEBUG(*args)
        return 0

    @staticmethod
    def fatal(*args):
        t = ' '.join(args)
        print('fatal: ' + t)
        print('abort')
        print()
        sys.exit(1)
        return 0

    @staticmethod
    def symbol_error(grammar, symbol, *args):
        text = ' '.join(args)
        fn, line_num = grammar.anchor_get(symbol)
        return internal.echo_error(text, fn, line_num)

    @staticmethod
    def symbol_warning(grammar, symbol, *args):
        text = ' '.join(args)
        fn, line_num = grammar.anchor_get(symbol)
        return internal.echo_warning(text, fn, line_num)

    @staticmethod
    def symbol_set_to_string(s):
        t = []
        if len(s) == 0:
            return '{ }'
        for n in s:
            t.append((str(n) == '') and '<empty>' or str(n))
        return '{ %s }'%(', '.join(t),)

    @staticmethod
    def rule_error(grammar, production, *args):
        text = ' '.join(args)
        fn, line_num = grammar.anchor_get(production)
        return internal.echo_error(text, fn, line_num)

    @staticmethod
    def rule_warning(grammar, production, *args):
        text = ' '.join(args)
        fn, line_num = grammar.anchor_get(production)
        return internal.echo_warning(text, fn, line_num)

    @staticmethod
    def bfs(initial, expand):
        open_list = collections.deque(list(initial))
        visited = set(open_list)
        while open_list:
            node = open_list.popleft()
            yield node
            for child in expand(node):
                if child not in visited:
                    open_list.append(child)
                    visited.add(child)
        return 0


#----------------------------------------------------------------------
# cstring lib
#----------------------------------------------------------------------
class cstring (object):

    @staticmethod
    def string_to_int(text, round = 0):
        text = text.strip('\r\n\t ').lstrip('+')
        minus = False
        if text.startswith('-'):
            minus = True
            text = text.lstrip('-')
        if text.startswith('0x'):
            round = 16
        elif text.startswith('0b'):
            round = 2
        text = text.rstrip('uUlLbB')
        try:
            # 进制转化
            x = int(text, round)
        except:
            x = 0
        if minus:
            x = -x
        return x

    @staticmethod
    def string_to_bool(text, defval = False):
        if text is None:
            # defval 返回布尔的默认值
            return defval
        text = text.strip('\r\n\t ')
        if text == '':
            return defval
        if text.lower() in ('true', '1', 'yes', 't', 'enable'):
            return True
        if text.lower() in ('0', 'false', 'no', 'n', 'f', 'disable'):
            return False
        x = cstring.string_to_int(text)
        if text.isdigit() or x != 0:
            return (x != 0) and True or False
        return defval

    @staticmethod
    def string_to_float(text):
        text = text.strip('\r\n\t ').rstrip('f')
        # 以小数点开头的，在小数点前面补零. 如：.12 -> 0.12
        if text.startswith('.'):
            text = '0' + text
        try:
            x = float(text)
        except:
            x = 0.0
        return x

    # 去掉引号
    @staticmethod
    def string_unquote(text):
        text = text.strip("\r\n\t ")
        if len(text) < 2:
            return text.replace('"', '').replace("'", '')
        # 去掉开头的引号
        mark = text[0]
        if mark not in ('"', "'"):
            return text.replace('"', '').replace("'", '')
        if text[-1] != mark:
            return text.replace('"', '').replace("'", '')
        # 最左右存在引号
        pos = 1
        output = []
        size = len(text)
        m = {'\\n': '\n', '\\t': '\t', '\\"': '"',
             "\\'": "\\'", '\\r': '\r', '\\\\': '\\',
             }
        while pos < size - 1:
            ch = text[pos]
            if ch == '\\':
                nc = text[pos:pos + 2]
                pos += 2
                if nc == '\\u':
                    u = text[pos:pos + 4]
                    pos += 4
                    try:
                        x = int('0x' + u, 16)
                    except:
                        x = ord('?')
                    output.append(chr(x))
                elif nc == '\\x':
                    u = text[pos:pos + 2]
                    pos += 2
                    try:
                        x = int('0x' + u, 16)
                    except:
                        x = ord('?')
                    output.append(chr(x))
                elif nc in m:
                    output.append(m[nc])
                else:
                    output.append(nc)
            else:
                output.append(ch)
                pos += 1
        return ''.join(output)

    @staticmethod
    def string_quote(text, escape_unicode = False):
        output = []
        output.append("'")
        for ch in text:
            cc = ord(ch)
            if ch == "'":
                output.append("\\'")
            elif (cc >= 256 and escape_unicode):
                nc = hex(ord(ch))[2:]
                nc = nc.rjust(4, '0')
                output.append('\\u' + nc)
            elif (cc >= 128 and escape_unicode) or cc < 32:
                nc = hex(cc)[2:]
                nc = nc.rjust(2, '0')
                output.append('\\x' + nc)
            else:
                output.append(ch)
        output.append("'")
        return ''.join(output)

    @staticmethod
    def quoted_normalize(text, double = False):
        text = text.strip('\r\n\t ')
        if len(text) == 0:
            return ''
        mark = text[0]
        if mark not in ('"', "'"):
            return None
        if len(text) < 2:
            return None
        if text[-1] != mark:
            return None
        size = len(text)
        pos = 1
        newmark = (not double) and "'" or '"'
        output = []
        output.append(newmark)
        while pos < size - 1:
            ch = text[pos]
            if mark == "'" and ch == '"':
                nc = newmark == "'" and '"' or '\\"'
                output.append(nc)
                pos += 1
            elif mark == '"' and ch == "'":
                nc = newmark == '"' and "'" or "\\'"
                output.append(nc)
                pos += 1
            elif ch == mark:
                nc = newmark == ch and ('\\' + ch) or ch
                output.append(nc)
                pos += 1
            elif ch == newmark:
                nc = '\\' + ch
                output.append(nc)
                pos += 1
            elif ch != '\\':
                output.append(ch)
                pos += 1
            else:
                nc = text[pos:pos + 2]
                pos += 2
                if newmark == '"' and nc == "\\'":
                    nc = "'"
                elif newmark == "'" and nc == '\\"':
                    nc = '"'
                elif nc == '\\':
                    nc = '\\\\'
                output.append(nc)
        output.append(newmark)
        return ''.join(output)

    @staticmethod
    def string_is_quoted(text):
        if len(text) < 2:
            return False
        mark = text[0]
        if mark not in ('"', "'"):
            return False
        if text[-1] != mark:
            return False
        return True

    @staticmethod
    def load_file_content(filename, mode = 'r'):
        if hasattr(filename, 'read'):
            try: content = filename.read()
            except: pass
            return content
        try:
            fp = open(filename, mode)
            content = fp.read()
            fp.close()
        except:
            content = None
        return content

    @staticmethod
    def load_file_text(filename, encoding = None):
        content = cstring.load_file_content(filename, 'rb')
        if content is None:
            return None
        if content[:3] == b'\xef\xbb\xbf':
            text = content[3:].decode('utf-8')
        elif encoding is not None:
            text = content.decode(encoding, 'ignore')
        else:
            text = None
            guess = [sys.getdefaultencoding(), 'utf-8']
            if sys.stdout and sys.stdout.encoding:
                guess.append(sys.stdout.encoding)
            try:
                import locale
                guess.append(locale.getpreferredencoding())
            except:
                pass
            visit = {}
            for name in guess + ['gbk', 'ascii', 'latin1']:
                if name in visit:
                    continue
                visit[name] = 1
                try:
                    text = content.decode(name)
                    break
                except:
                    pass
            if text is None:
                text = content.decode('utf-8', 'ignore')
        return text

    @staticmethod
    def tabulify (rows, style = 0, align = "left"):
        colsize = {}
        maxcol = 0
        output = []
        if not rows:
            return ''
        for row in rows:
            maxcol = max(len(row), maxcol)
            for col, text in enumerate(row):
                text = str(text)
                size = len(text)
                if col not in colsize:
                    colsize[col] = size
                else:
                    colsize[col] = max(size, colsize[col])
        if maxcol <= 0:
            return ''
        def gettext(row, col):
            # cell 的长度为 2 + cszie, 左右边距为 1
            csize = colsize[col]
            if row >= len(rows):
                return ' ' * (csize + 2)
            row = rows[row]
            if col >= len(row):
                return ' ' * (csize + 2)
            text = str(row[col])
            padding = (2 + csize) - len(text)
            # align default to left
            pad1 = 1
            pad2 = padding - pad1
            if align == "right":
                pad2 = 1
                pad1 = padding - pad2
            elif align == "center":
                pad1 = int(padding / 2) # padding 至少为 2
                pad2 = padding - pad1
            return (' ' * pad1) + text + (' ' * pad2)
        if style == 0:
            for y, row in enumerate(rows):
                line = ''.join([ gettext(y, x) for x in range(maxcol) ])
                output.append(line)
        elif style == 1:
            if rows:
                # 在第一行数组后面插入标题分隔符
                newrows = rows[:1]
                head = [ '-' * colsize[i] for i in range(maxcol) ]
                newrows.append(head)
                newrows.extend(rows[1:])
                rows = newrows
            for y, row in enumerate(rows):
                line = ''.join([ gettext(y, x) for x in range(maxcol) ])
                output.append(line)
        elif style == 2:
            sep = '+'.join([ '-' * (colsize[x] + 2) for x in range(maxcol) ])
            sep = '+' + sep + '+'
            for y, row in enumerate(rows):
                output.append(sep)
                line = '|'.join([ gettext(y, x) for x in range(maxcol) ])
                output.append('|' + line + '|')
            output.append(sep)
        return '\n'.join(output)

    # match string and return matched text and remain text
    @staticmethod
    def string_match(source, pattern, group = 0):
        m = re.match(pattern, source)
        if m:
            matched = m.group(group)
            span = m.span()
            return matched, source[span[1]:]
        return None, source


#----------------------------------------------------------------------
# lex analyze
#----------------------------------------------------------------------
class GrammarLex (object):

    def __init__ (self):
        self.specific = self._build_pattern()

    def _build_pattern (self):
        spec = [
                    # (回调函数|None|Token Name，匹配规则)
                    # (回调函数|None|Token Name，匹配规则, 输入回调额外参数)
                    # None 表示忽略
                    # 忽略注释, 无回调函数
                    (None, PATTERN_COMMENT1),       # ignore
                    (None, PATTERN_COMMENT2),       # ignore
                    (None, PATTERN_COMMENT3),       # ignore
                    (None, PATTERN_WHITESPACE),     # ignore
                    (self._handle_string, PATTERN_STRING1),
                    (self._handle_string, PATTERN_STRING2),
                    (self._handle_macro, PATTERN_GMACRO),
                    (self._handle_integer, PATTERN_CINTEGER),
                    (self._handle_float, PATTERN_NUMBER),
                    ('BAR', r'\|'),         # 产生式或符号
                    ('END', r'[;]'),        # 产生式结尾
                    (':', r'[:]'),          # 产生式分隔符
                    ('LEX', r'[@].*'),      # 词法
                    ('NAME', PATTERN_GNAME),
                    ('NAME', PATTERN_NAME),
                    (self._handle_action, r'\{[^\{\}]*\}'),
                    (None, r'\%\%'),
                    ('OPERATOR', r'[\+\-\*\/\?\%]'),
                    ('MISMATCH', r'.'),
                ]
        return spec

    def _handle_string (self, value):
        text = cstring.quoted_normalize(value)
        return ('STRING', text)

    def _handle_integer (self, value):
        return ('NUMBER', cstring.string_to_int(value))

    def _handle_float (self, value):
        if '.' not in value:
            return self._handle_integer(value)
        return ('NUMBER', cstring.string_to_float(value))

    def _handle_macro (self, value):
        value = value.strip('\r\n\t ').replace(' ', '')
        return ('MACRO', value)

    def _handle_action (self, value):
        value = value.strip('\r\n\t ')
        return ('ACTION', value)

    def process (self, source):
        tokens = {}     # line no -> token list
        for token in tokenize(source, self.specific):
            # print(repr(token))
            line_num = token.line
            tokens.setdefault(line_num, []).append(token)
            # print(token)
        # print(tokens)
        return tokens


#----------------------------------------------------------------------
# load grammar file
#----------------------------------------------------------------------
class GrammarLoader (object):

    def __init__ (self):
        self.line_num = 0
        self.file_name = ''
        self.code = 0
        self.source = ''
        self.precedence = 0
        self.srcinfo = {}           # token value -> (file name, line no) ; record first appearance
        self.lex = GrammarLex()

    def error (self, *args):
        text = ' '.join(args)
        fn = (not self.file_name) and '<buffer>' or self.file_name
        internal.echo_error(text, fn, self.line_num)
        return 0

    def error_token (self, token, text = None):
        fn = (not self.file_name) and '<buffer>' or self.file_name
        if text is None:
            text = 'unexpected token: %r'%(token.value, )
        internal.echo_error(text, fn, token.line, token.column)
        return 0

    def load (self, source, file_name = ''):
        if isinstance(source, str):
            self.source = source
        else:
            self.source = source.read()
            if isinstance(self.code, bytes):
                self.code = self.code.decode('utf-8', 'ignore')
        self.file_name = file_name and file_name or '<buffer>'
        # hr: hResult, here's the result，API 的返回值
        hr = self._scan_grammar()
        if hr != 0:
            print('loading failed %d'%hr)
            return None
        return self.g

    def load_from_file (self, file_name, encoding = None):
        if not os.path.exists(file_name):
            raise FileNotFoundError('No such file: %r'%file_name)
        self.source = cstring.load_file_text(file_name, encoding)
        self.file_name = file_name
        hr = self._scan_grammar()
        if hr != 0:
            print('loading failed %d'%hr)
            return None
        return self.g

    def _scan_grammar (self):
        self.g = Grammar()
        self.g.start = None
        self.current_symbol = None
        self.line_num = 0
        self.precedence = 0
        self._cache = []
        self.srcinfo.clear()
        tokens = self.lex.process(self.source)
        keys = list(tokens.keys())
        keys.sort()
        for line_num in keys:
            self.line_num = line_num
            args = tokens[line_num]
            # 返回异常值
            hr = 0
            if not args:
                continue
            if args[0].name == 'MACRO':
                hr = self._process_macro(args)
            elif args[0].name == 'LEX':
                hr = self._process_lexer(args)
            else:
                hr = self._process_grammar(args)
            if hr != 0:
                return hr
        if len(self._cache) > 0:
            self._process_rule(self._cache)
        self.g.update()
        # 第一个产生式的左边作为文法的开头
        if self.g.start is None:
            if len(self.g.production) > 0:
                self.g.start = self.g.production[0].head
        if self.g.start:
            symbol = self.g.start.__copy__()
            symbol.term = (symbol.name in self.g.terminal)
            self.g.start = symbol
        for n in self.srcinfo:
            if not self.g.anchor_has(n):
                t = self.srcinfo[n]
                self.g.anchor_set(n, t[0], t[1])
        self.g.file_name = self.file_name
        return 0

    def _process_grammar (self, args):
        for arg in args:
            self._cache.append(arg)
            if arg.name == 'END':
                hr = self._process_rule(self._cache)
                self._cache.clear()
                if hr != 0:
                    return hr
        return 0

    def _process_rule (self, args):
        if not args:
            return 0
        # 拷贝 args
        argv = [n for n in args]
        if argv[0].name == 'STRING':
            self.error_token(argv[0], 'string literal %s can not have a rule'%argv[0].value)
            return 1
        # 每个产生式开头必须是 'NAME' 类型，即非终结符
        elif argv[0].name != 'NAME':
            self.error_token(argv[0], 'wrong production head: "%s"'%argv[0].value)
            return 1
        # 每个产生式结尾必须是 'END' 类型，即;
        elif argv[-1].name != 'END':
            self.error_token(argv[-1], 'missing ";"')
            return 2
        head = load_symbol(argv[0].value)
        # 去掉产生式结尾符号;
        argv = argv[:-1]
        # 产生式的长度(除了结尾符号)必须大于1
        #   head : [body] ;
        if len(argv) < 2:
            self.error_token(argv[0], 'require ":" after "%s"'%(argv[0].value))
            return 3
        # 产生式分隔符
        elif argv[1].name != ':':
            self.error_token(argv[1], 'require ":" before "%s"'%(argv[1].value))
            return 4
        cache = []
        # 产生式右边
        for arg in argv[2:]:
            if arg.name == 'BAR':   # 产生式或符号 |
                # hr 返回异常值
                hr = self._add_rule(head, cache)
                cache.clear()
                if hr != 0:
                    return hr
            else:
                cache.append(arg)
        hr = self._add_rule(head, cache)
        if hr != 0:
            return hr
        if not self.g.anchor_has(head):
            self.g.anchor_set(head, self.file_name, argv[0].line)
        return 0

    def _add_rule (self, head, argv):
        body = []
        # print('add', head, ':', argv)
        pos = 0
        size = len(argv)
        action = {}
        precedence = None
        while pos < size:
            token = argv[pos]
            # 将一个产生式右边的非终结符和终结符加入到 body, 生成 Production 对象
            # Type STRING is terminal
            if token.name == 'STRING':
                text = token.value
                value = cstring.string_unquote(text)
                if not value:
                    pos += 1
                    continue
                elif len(text) < 2:
                    self.error_token(token, 'bad string format %s'%text)
                    return 10
                elif len(text) == 2:
                    pos += 1
                    continue
                symbol = load_symbol(token.value)
                body.append(symbol)
                pos += 1
                # push terminal
                self.g.push_token(symbol)
            # Type NAME is non-terminal
            elif token.name == 'NAME':
                symbol = load_symbol(token.value)
                body.append(symbol)
                pos += 1
            # 以上的 token 加入到 body
            elif token.name == 'MACRO':
                cmd = token.value.strip()
                pos += 1
                if cmd == '%prec':
                    token = argv[pos]
                    prec = token.value
                    pos += 1
                    if prec not in self.g.precedence:
                        self.error_token(token, 'undefined precedence %s'%prec)
                        return 11
                    precedence = prec
                elif cmd in ('%empty', '%e', '%epsilon'):
                    pos += 1
                    continue
            elif token.name == 'ACTION':
                i = len(body)
                act = (token.value, i)
                action.setdefault(i, []).append(act)
                pos += 1
            elif token.name == 'NUMBER':
                self.error_token(token)
                return 11
            elif token.name == 'OPERATOR':
                self.error_token(token)
                return 12
            elif token.name == 'MISMATCH':
                self.error_token(token)
                return 13
            else:
                self.error_token(token)
                return 14
            pass
        p = Production(head, body)
        p.precedence = precedence
        if len(action) > 0:
            p.action = action
        # print('action:', action)
        self.g.append(p)
        for token in argv:
            if token.value not in self.srcinfo:
                t = (self.file_name, token.line)
                self.srcinfo[token.value] = t
        if argv:
            self.g.anchor_set(p, self.file_name, argv[0].line)
        return 0

    def _process_macro (self, args):
        macro = args[0]
        argv = args[1:]
        cmd = macro.value
        # define terminal, append to self.terminal
        if cmd == '%token':
            for n in argv:
                if n.name != 'NAME':
                    self.error_token(n)
                    return 1
                self.g.push_token(n.value)
        elif cmd in ('%left', '%right', '%nonassoc', '%precedence'):
            assoc = cmd[1:].strip()
            for n in argv:
                if n.name not in ('NAME', 'STRING'):
                    # print('fuck', n)
                    self.error_token(n)
                    return 1
                self.g.push_precedence(n.value, self.precedence, assoc)
            self.precedence += 1
        elif cmd == '%start':
            if len(argv) == 0:
                self.error_token(macro, 'expect start symbol')
                return 2
            token = argv[0]
            if token.name in ('STRING',):
                self.error_token(token, 'can not start from a terminal')
                return 3
            elif token.name != 'NAME':
                self.error_token(token, 'must start from a non-terminal symbol')
                return 4
            symbol = load_symbol(argv[0].value)
            if symbol.name in self.g.terminal:
                symbol.term = True
            if symbol.term:
                self.error_token(token, 'could not start from a terminal')
                return 5
            self.g.start = symbol
        return 0

    def _process_lexer (self, args):
        assert len(args) == 1
        args[0].column = -1
        origin: str = args[0].value.strip('\r\n\t ')
        m = re.match(r'[@]\s*(\w+)', origin)
        if m is None:
            self.error_token(args[0], 'bad lex declaration')
            return 1
        head: str = ('@' + m.group(1)).strip('\r\n\t ')
        body: str = origin[m.span()[1]:].strip('\r\n\t ')
        if head in ('@ignore', '@skip'):
            if not validate_pattern(body):
                self.error_token(args[0], 'bad regex pattern: ' + repr(body))
                return 2
            self.g.push_scanner(('ignore', body))
        elif head == '@match':
            m = re.match(r'(\{[^\{\}]*\}|\w+)\s+(.*)', body)
            if m is None:
                self.error_token(args[0], 'bad lex matcher definition')
                return 3
            name = m.group(1).strip('\r\n\t ')
            pattern = m.group(2).strip('\r\n\t ')
            if not validate_pattern(pattern):
                self.error_token(args[0], 'bad regex pattern: ' + repr(pattern))
                return 4
            # print('matched name=%r patterm=%r'%(name, pattern))
            self.g.push_scanner(('match', name, pattern))
            if not name.startswith('{'):
                self.g.push_token(name)
        elif head == '@import':
            part = re.split(r'\W+', body)
            part = list(filter(lambda n: (n.strip('\r\n\t ') != ''), part))
            if len(part) == 1:
                name = part[0].strip()
                if not name:
                    self.error_token(args[0], 'expecting import name')
                    return 5
                if name not in PATTERN:
                    self.error_token(args[0], 'invalid import name "%s"'%name)
                    return 6
                self.g.push_scanner(('import', name, name))
                if not name.startswith('{'):
                    self.g.push_token(name)
            elif len(part) == 3:
                name = part[0].strip()
                if not name:
                    self.error_token(args[0], 'expecting import name')
                    return 7
                asname = part[2].strip()
                if not asname:
                    self.error_token(args[0], 'expecting aliasing name')
                    return 8
                if part[1].strip() != 'as':
                    self.error_token(args[0], 'invalid import statement')
                    return 9
                if name not in PATTERN:
                    self.error_token(args[0], 'invalid import name "%s"'%name)
                    return 10
                self.g.push_scanner(('import', asname, name))
                if not asname.startswith('{'):
                    self.g.push_token(asname)
        else:
            self.error_token(args[0], 'bad lex command: %r'%head)
        return 0


#----------------------------------------------------------------------
# load from file
#----------------------------------------------------------------------
def load_from_file(filename) -> Grammar:
    loader = GrammarLoader()
    g = loader.load_from_file(filename)
    if g is None:
        sys.exit(1)
    return g


#----------------------------------------------------------------------
# load from string
#----------------------------------------------------------------------
def load_from_string(code) -> Grammar:
    loader = GrammarLoader()
    g = loader.load(code)
    if g is None:
        sys.exit(1)
    return g


#----------------------------------------------------------------------
# marks
#----------------------------------------------------------------------
MARK_UNVISITED = 0
MARK_VISITING = 1
MARK_VISITED = 2

EPSILON = Symbol('', False)
EOF = Symbol('$', True)
PSHARP = Symbol('#', True)  # P SHARP(#) is not in grammar


#----------------------------------------------------------------------
# 符号信息
#----------------------------------------------------------------------
class SymbolInfo (object):

    """example
    F : '-';            F not has epsilon and not is epsilon; has_epsilon = False, is_epsilon = True
    E : epsilon '+';    E has epsilon but not is epsilon; has_epsilon = True, is_epsilon = False
    T : ;               T has epsilon and is epsilon; has_epsilon = True, is_epsilon = True
    """
    def __init__ (self, symbol):
        self.symbol = symbol
        self.mark = MARK_UNVISITED
        self.rules = []
        self.rule_number = 0
        self.is_epsilon = None
        self.has_epsilon = None     # has epsilon but maybe not is epsilon

    def __copy__ (self):
        obj = SymbolInfo(self.symbol)
        return obj

    def __deepcopy__ (self, memo):
        return self.__copy__()

    @property
    def is_terminal (self):
        return self.symbol.term

    @property
    def name (self):
        return self.symbol.name

    def reset (self):
        self.mark = MARK_UNVISITED

    def check_epsilon (self):
        if len(self.rules) == 0:
            return 1
        count = 0
        for rule in self.rules:
            if rule.is_epsilon:
                count += 1
        if count == len(rule):
            return 2
        if count > 0:
            return 1
        return 0


#----------------------------------------------------------------------
# analyzer
#----------------------------------------------------------------------
class GrammarAnalyzer (object):

    def __init__ (self, g: Grammar):
        assert g is not None
        self.g = g                  # Grammar
        self.info = {}              # symbol name -> SymbolInfo
        self.epsilon = Symbol('')
        self.FIRST = {}
        self.FOLLOW = {}
        self.SELECT = {}
        self.terminal = {}
        self.nonterminal = {}
        self.verbose = 2

    def process (self, expand_action = True):
        if expand_action:
            self.__argument_semantic_action()
        if self.g._dirty:
            self.g.update()
        self.__build_info()
        self.__update_epsilon()
        self.__update_first_set()
        self.__update_follow_set()
        self.__update_select_set()
        self.__check_integrity()
        return 0

    def __build_info (self):
        self.info.clear()
        self.terminal.clear()
        self.nonterminal.clear()
        g = self.g
        for name in g.symbol:
            info = SymbolInfo(g.symbol[name])
            self.info[name] = info
            info.reset()
            rules = g.rule.get(name, [])
            info.rule_number = len(rules)
            info.rules = rules
            if info.is_terminal:
                self.terminal[info.name] = info.symbol
            else:
                self.nonterminal[info.name] = info.symbol
        return 0

    '''
    https://zhuanlan.zhihu.com/p/31301086
    基本情况
        X -> a Y
            FIRST(X) U= {a}
    归纳情况
        X -> Y1 ... Yn
            FIRST(X) U= FIRST(Y1), add FIRST(Y1) to FRIST(X)
            if Y1 -> ε, FIRST(X) U= FIRST(Y2)
            if Y1, Y2 -> ε,, FIRST(X) U= FIRST(Y3)
    ......

    FIRST 集的完整不动点算法:
    foreach (symbol S)
        if (S is terminal T)
            FIRST(T) = {T}      # T: terminal
        else (S is non-terminal)
            FIRST(N) = {}       # N: non-terminal

    while 1     # some set is changing  某一些符号的集合还在增大
        change = 0
        foreach (production p: N -> β1 ... βn)
            foreach (βi from β1 upto βn)
                if (βi == a ...)   # terminal
                    if (a not in FIRST(N))  # FIRST(N) 集合中没有 a
                        FIRST(N) U= {a}
                        change += 1         # 说明集合已经增大
                    break
                if (βi == M ...)   # non-terminal
                    if (FIRST(N) U FIRST(M) != FIRST(N))    # FIRST(N) 集合没有包含 FIRST(M)
                        FIRST(N) U= FIRST(M)
                        change += 1         # 说明集合已经增大
                if (ε is not in FIRST(M))
                    break
        if (not change)
            break
    '''
    def __update_first_set (self):
        self.FIRST.clear()
        for name in self.g.symbol:
            symbol = self.g.symbol[name]
            if symbol.term:
                self.FIRST[name] = set([name])
            else:
                self.FIRST[name] = set()
        self.FIRST['$'] = set(['$'])
        self.FIRST['#'] = set(['#'])
        while 1:
            changes = 0
            for symbol in self.nonterminal:
                info = self.info[symbol]
                for rule in info.rules:
                    first = self.__calculate_first_set(rule.body)
                    # add terminal, which not in self.FIRST, in "first" to "self.FIRST"
                    for n in first:
                        # 如果 n 不存在 first 集合中，加入集合中并且标注已经被修改过
                        if n not in self.FIRST[symbol]:
                            self.FIRST[symbol].add(n)
                            changes += 1
            if not changes:
                break
        return 0

    def __calculate_first_set (self, vector):
        output = set([])
        index = 0
        for symbol in vector:
            if symbol.term:
                output.add(symbol.name)
                break
            # symbol is non-terminal
            if symbol.name not in self.FIRST:
                for key in self.FIRST.keys():
                    print('FIRST:', key)
                raise ValueError('FIRST set does not contain %r'%symbol.name)
            # add terminal to first except epsilon
            for name in self.FIRST[symbol.name]:
                if name != EPSILON:
                    output.add(name)
            # if left body of production has epsilon, continue to find
            if EPSILON not in self.FIRST[symbol.name]:
                break
            index += 1
        if index >= len(vector):
            output.add(EPSILON.name)
        return output

    '''
    FOLLOW 集的不动点算法:
    foreach (nonterminal N)
        FOLLOW(N) = {}
    while 1     # (some set is changing)
        change = 0
        foreach (production p: N -> β1 ... βn)
            temp = FOLLOW(N)     # temp 记录在 βn 的后面
            foreach (βi from βn downto β1)   # 逆序 !!! 逆序的 FOLLOW。
                if (βi == a...)  # terminal
                    temp = {a}
                if (βi == M ...)    # non-terminal
                    if (temp not in FOLLOW(M))
                        FOLLOW(M) U= temp
                        change += 1
                    if (ε is not in FIRST(M))
                        temp = FIRST(M)
                    else
                        temp U= FIRST(M)   # 如果 M 是 NULLABLE, 那么我们不仅仅能看
                                           # 到FIRST(M),还能 M 的FIRST(M)后面的元素，
                                           # 也就是非最右项的其余右项。
        if (not change)
            break
    '''
    def __update_follow_set (self):
        self.FOLLOW.clear()
        start = self.g.start
        if not self.g.start:
            if len(self.g) > 0:
                start = self.g[0].head
        if not start:
            internal.echo_error('start point is required')
            return 0
        FOLLOW = self.FOLLOW
        for n in self.nonterminal:
            FOLLOW[n] = set([])
        FOLLOW[start.name] = set(['$'])
        while 1:
            changes = 0
            for p in self.g:
                for i, symbol in enumerate(p.body):
                    # skip leftmost terminal
                    if symbol.term:
                        continue
                    follow = p.body[i + 1:]
                    first = self.vector_first_set(follow)
                    epsilon = False
                    # follow(head) add follow(symbol) if epsilon in first set which follows symbol
                    for n in first:
                        if n != EPSILON.name:
                            if n not in FOLLOW[symbol.name]:
                                FOLLOW[symbol.name].add(n)
                                changes += 1
                        else:
                            epsilon = True
                    if epsilon or i == len(p.body) - 1:
                        for n in FOLLOW[p.head]:
                            if n not in FOLLOW[symbol.name]:
                                FOLLOW[symbol.name].add(n)
                                changes += 1
            if not changes:
                break
        return 0

    def __update_select_set (self):
        for i, p in enumerate(self.g):
            first = self.vector_first_set(p.body)
            if not '' in first:
                self.SELECT[i] = first
            else:
                self.SELECT[i] = (first - set([''])) | self.FOLLOW[p.head]

    def is_LL1 (self):
        for rule in self.g.rule.values():
            if len(rule) <= 1:
                continue
            select = []
            for p in rule:
                select.append((p.index, self.SELECT[p.index]))
            for i in range(len(select)):
                for j in range(i):
                    if select[i][1] & select[j][1]:
                        return False
        return True

    def __update_epsilon (self):
        g = self.g
        for info in self.info.values():
            if info.symbol.term:
                info.is_epsilon = False
                info.has_epsilon = False
                info.mark = MARK_VISITED
            elif len(info.rules) == 0:
                info.is_epsilon = False
                info.has_epsilon = False
                info.mark = MARK_VISITED
            else:
                is_count = 0
                size = len(info.rules)
                for p in info.rules:
                    if p.is_epsilon:
                        is_count += 1
                if is_count >= size:
                    info.is_epsilon = True
                    info.has_epsilon = True
                    info.mark = MARK_VISITED
                elif is_count > 0:
                    info.has_epsilon = True

        while True:
            count = 0
            for p in g.production:
                count += self.__update_epsilon_production(p)
            for info in self.info.values():
                count += self.__update_epsilon_symbol(info)
            if not count:
                break
        return 0

    def __update_epsilon_symbol (self, info: SymbolInfo):
        count = 0
        if info.symbol.term:
            return 0
        elif info.is_epsilon is not None:
            if info.has_epsilon is not None:
                return 0
        is_count = 0
        isnot_count = 0
        has_count = 0
        hasnot_count = 0
        for p in info.rules:
            if p.is_epsilon:
                is_count += 1
            elif p.is_epsilon is not None:
                isnot_count += 1
            if p.has_epsilon:
                has_count += 1
            elif p.has_epsilon is not None:
                hasnot_count += 1
        size = len(info.rules)
        if info.is_epsilon is None:
            if is_count >= size:
                info.is_epsilon = True
                info.has_epsilon = True
                count += 1
            elif isnot_count >= size:
                info.is_epsilon = False
                info.has_epsilon = False
                count += 1
        if info.has_epsilon is None:
            if has_count > 0:
                info.has_epsilon = True
                count += 1
            elif hasnot_count >= size:
                info.has_epsilon = False
                count += 1
        return count

    def __update_epsilon_production (self, p: Production):
        count = 0
        if (p.is_epsilon is not None) and (p.has_epsilon is not None):
            return 0
        if p.leftmost_terminal() is not None:
            if p.is_epsilon is None:
                p.is_epsilon = False
                count += 1
            if p.has_epsilon is None:
                p.has_epsilon = False
                count += 1
            return count
        is_count = 0
        isnot_count = 0
        has_count = 0
        hasnot_count = 0
        for n in p.body:
            info = self.info[n.name]
            if info.is_epsilon:
                is_count += 1
            elif info.is_epsilon is not None:
                isnot_count += 1
            if info.has_epsilon:
                has_count += 1
            elif info.has_epsilon is not None:
                hasnot_count += 1
        if p.is_epsilon is None:
            if is_count >= len(p.body):
                p.is_epsilon = True
                p.has_epsilon = True
                count += 1
            elif isnot_count > 0:
                p.is_epsilon = False
                count += 1
        if p.has_epsilon is None:
            if has_count >= len(p.body):
                p.has_epsilon = True
                count += 1
            elif hasnot_count > 0:
                p.has_epsilon = False
                count += 1
        return count

    def vector_is_epsilon (self, vector: Vector):
        if vector.leftmost_terminal() is not None:
            return False
        is_count = 0
        isnot_count = 0
        for symbol in vector:
            if symbol.name not in self.info:
                continue
            info = self.info[symbol.name]
            if info.is_epsilon:
                is_count += 1
            elif info.is_epsilon is not None:
                isnot_count += 1
        if is_count >= len(vector):
            return True
        return False

    def vector_has_epsilon (self, vector: Vector):
        if vector.leftmost_terminal() is not None:
            return False
        is_count = 0
        isnot_count = 0
        has_count = 0
        hasnot_count = 0
        for symbol in vector:
            if symbol.name not in self.info:
                continue
            info = self.info[symbol.name]
            if info.is_epsilon:
                is_count += 1
            elif info.is_epsilon is not None:
                isnot_count += 1
            if info.has_epsilon:
                has_count += 1
            elif info.has_epsilon is not None:
                hasnot_count += 1
        size = len(vector)
        if (is_count >= size) or (has_count >= size):
            return True
        return False

    def vector_first_set (self, vector):
        return self.__calculate_first_set(vector)

    def __integrity_error (self, *args):
        text = ' '.join(args)
        internal.echo_error('integrity: ' + text)
        return 0

    def symbol_error (self, symbol, *args):
        if self.verbose < 1:
            return 0
        if symbol is None:
            return internal.echo_error(' '.join(args), self.g.file_name, 1)
        return internal.symbol_error(self.g, symbol, *args)

    def symbol_warning (self, symbol, *args):
        if self.verbose < 2:
            return 0
        if symbol is None:
            return internal.echo_warning(' '.join(args), self.g.file_name, 1)
        return internal.symbol_warning(self.g, symbol, *args)

    def __check_integrity (self):
        error = 0
        for info in self.info.values():
            symbol = info.symbol
            if symbol.term:
                continue
            name = symbol.name
            first = self.FIRST[name]
            if EPSILON.name in first:
                if len(first) == 1:
                    if not info.is_epsilon:
                        t = 'symbol %s is not epsilon but '%name
                        t += 'first set only contains epsilon'
                        self.__integrity_error(t)
                        error += 1
                    if not info.has_epsilon:
                        t = 'symbol %s has not epsilon but '%name
                        t += 'first set only contains epsilon'
                        self.__integrity_error(t)
                        error += 1
                elif len(first) > 0:
                    if info.is_epsilon:
                        t = 'symbol %s is epsilon but '%name
                        t += 'first set contains more than epsilon'
                        self.__integrity_error(t)
                        error += 1
                    if not info.has_epsilon:
                        t = 'symbol %s has not epsilon but '%name
                        t += 'first set contains epsilon'
                        self.__integrity_error(t)
                        error += 1
            else:
                if info.is_epsilon:
                    t = 'symbol %s is epsilon but '%name
                    t += 'first set does not contains epsilon'
                    self.__integrity_error(t)
                    error += 1
                if info.has_epsilon:
                    t = 'symbol %s has epsilon but '%name
                    t += 'first set does not contains epsilon'
                    self.__integrity_error(t)
                    error += 1
        if error and 0:
            sys.exit(1)
        return error

    def clear_mark (self, init = MARK_UNVISITED):
        for info in self.info.values():
            info.mark = init
        return 0

    def __iter_child (self, symbol):
        if symbol in self.g.rule:
            for rule in self.g.rule[symbol]:
                for n in rule.body:
                    yield n.name
        return None

    def find_reachable (self, parents):
        output = []
        if parents is None:
            if self.g.start is None:
                return set()
            roots = self.g.start.name
        elif isinstance(parents, str):
            roots = [parents]
        elif isinstance(parents, Symbol):
            roots = [parents.name]
        else:
            roots = parents
        for symbol in internal.bfs(roots, self.__iter_child):
            output.append(symbol)
        return output

    def find_undefined_symbol (self):
        undefined = set([])
        # sname: symbol name
        for sname in self.g.symbol:
            if sname in self.g.terminal:
                continue
            if sname not in self.g.rule:
                if sname not in undefined:
                    undefined.add(sname)
            elif len(self.g.rule[sname]) == 0:
                if sname not in undefined:
                    undefined.add(sname)
        return list(undefined)

    # symbol can deduce production which only include terminals
    '''
    为什么要多次查找 ?
    例如文法:
        list: elem;
        elem: ID;
    第一趟只找到 elem;      terminated = [elem]
    第二趟才能找到 list;    terminated = [elem, list]
    '''
    def find_terminated_symbol (self):
        terminated = set([])
        for symbol in self.g.symbol.values():
            if symbol.term:
                terminated.add(symbol.name)
        while 1:
            changes = 0
            for symbol in self.g.symbol.values():
                if symbol.name in terminated:
                    continue
                elif symbol.name not in self.g.rule:
                    continue
                for rule in self.g.rule[symbol.name]:
                    can_terminate = True    # 产生式右边的符号都能推导出终结符
                    for n in rule.body:
                        if n.name not in terminated:
                            can_terminate = False
                            break
                    if can_terminate:
                        if symbol.name not in terminated:
                            terminated.add(symbol.name)
                            changes += 1
                        break
            if not changes:
                break
        return list(terminated)

    def check_grammar (self):
        self.error = 0
        self.warning = 0
        if len(self.g) == 0:
            self.symbol_error(None, 'no rules has been defined')
            self.error += 1
        for n in self.find_undefined_symbol():
            self.symbol_error(n, 'symbol %r is used, but is not defined as a token and has no rules'%n)
            self.error += 1
        smap = set(self.find_reachable(self.g.start))
        for symbol in self.g.symbol.values():
            if symbol.term:
                continue
            if symbol.name not in smap:
                self.symbol_warning(symbol, 'nonterminal \'%s\' useless in grammar'%symbol)
                self.warning += 1
        if self.g.start:
            if self.g.start.term:
                t = 'start symbol %s is a token'
                self.symbol_error(self.g.start, t)
                self.error += 1
            terminated = self.find_terminated_symbol()
            # print('terminated', terminated)
            if self.g.start.name not in terminated:
                t = 'start symbol %s does not derive any sentence'%self.g.start.name
                self.symbol_error(self.g.start, t)
                self.error += 1
        else:
            self.symbol_error(None, 'start symbol is not defined')
            self.error += 1
        return self.error

    # 将 L 型 SDT （即生成式里有语法动作的）转换为 S 型纯后缀的模式
    '''
    后缀SDT：所有动作都在产生式最右端的SDT

    1. S 属性的 SDD 翻译成 SDT 比较简单，所有产生的动作位于产生式的右端，也称后缀 SDT。
       因为 S 属性只包括综合属性，依赖于子结点，因此需要在所有的子结点全部分析处理完毕之后处理。

    2. L 属性的 SDD 翻译成 SDT 的规则如下：
        (1) 将计算某个非终结符号 A 的继承属性的动作插入到产生式右部中紧靠在 A 的本次出现之前的位置上；
        (2) 将计算一个产生式左部符号的综合属性的动作放在这个产生式右部的最右端

    如果 S-SDD 的基本文法可以使用 LR 分析技术，那么 SDT 可以在 LR 语法分析过程中实现。

    S-SDD                                           S-SDT
    Production          Action
    (1) L -> En         L.val = E.val               L -> En {L.val = E.val}
    (2) E -> E1 + T     E.val = E1.val + T.val      E -> E1 + T {E.val = E1.val + T.val}
    (3) E -> T          E.val = T.val               E -> T {E.val = T.val}
    (4) T -> T1 + F     T.val = T1.val x F.val      T -> T1 + F {T.val = T1.val x F.val}
    (5) T -> F          T.val = F.val               T -> F {T.val = F.val}
    (6) F -> ( E )      F.val = E.val               F -> ( E ) {F.val = E.val}
    (7) F -> digit      F.val = digit.lexval        F -> digit {F.val = digit.lexval}

    L-SDT 转 S-SDT:
    1. 将给定的基础文法为 LL 文法的 L 属性的 SDD 转换成 SDT，这样的 SDT 在每个非终结符号之前放置语义动作计算它的继承属性，并且在产生式最右端放置一个语义动作计算综合属性；
    2. 对每个内嵌的语义动作，向这个文法中引入一个标记非终结符号来替换它。每个这样的位置都有一个不同的标记，并且对于任意一个标记 M 都有一个产生式 M→ε；
    3. 如果标记非终结符号 M 在某个产生式 A→α{a}β 中替换了语义动作 a，对 a 进行修改得到 a’，并且将 a’关联到 M→ε 上。这个动作 a’将动作 a 需要的 A 或 α 中符号的任何属性作为 M 的继承属性进行拷贝，并且按照 a 中的方法计算各个属性，计算得到的属性将作为 M 的综合属性。

    L-SDT
    1) T  -> F {T'.inh = F.val} T' {T.val = T'.val}
    2) T' -> * F {T1'.inh = T1'.inh x F.val} T1' {T'.syn = T1'.syn}
    3) T' -> ε {T'.syn = T'.inh}
    4) F  -> digit {F.val = digit.lexval}

    S-SDT
    1) T  -> F M1 T' {T.val = T'.val}
       M1 -> ε {M1.i = F.val; M1.syn = M1.i}
    2) T' -> * F M2 T1' {T'.syn = T1'.syn}
       M2 -> ε {M2.i1 = T'.inh; M2.i2 = F.val; M2.syn = M2.i1 x M2.i2}
    3) T' -> ε {T'.syn = T'.inh}
    4) F  -> digit {F.val = digit.lexval}
    '''
    def __argument_semantic_action (self):
        rules = []
        anchors = []
        name_id = 1
        for rule in self.g.production:
            rule:Production = rule
            anchor = self.g.anchor_get(rule)
            # 有语义动作的产生式不放入 rules, 因为需要对当前含语义动作的产生式进行处理
            if not rule.action:
                rules.append(rule)
                anchors.append(anchor)
                continue
            count = 0
            for key in rule.action.keys():
                if key < len(rule):
                    count += 1
            if count == 0:
                rules.append(rule)
                anchors.append(anchor)
                continue
            # 处理内嵌语义动作
            body = []   # 当前产生式的右边，内嵌语义动作用标记 Mi 取代
            children = []   # 所有内嵌语义动作的标记 M 产生式
            # T -> F {T'.inh = F.val} T' {T.val = T'.val}
            for pos, symbol in enumerate(rule.body):
                if pos in rule.action:
                    head = Symbol('M@%d'%name_id, False)
                    name_id += 1
                    # M1 -> ε {M1.i = F.val; M1.syn = M1.i}
                    child = Production(head, [])    # M → ε
                    child.action = {}
                    child.action[0] = []
                    stack_pos = len(body)       # 记录非终结符 M 在产生式右边的位置
                    # T -> F {T'.inh = F.val} T' {T.val = T'.val}
                    #              ^                    ^
                    # stack_pos:   1                    3
                    # 产生式 M 在规约时, 计算 M 所在产生式右边的左侧属性
                    for act in rule.action[pos]:
                        child.action[0].append((act[0], stack_pos))
                    child.parent = len(rules)   # 产生式 M 的父类为所含非终结符 M 的产生式
                    children.append(child)
                    body.append(head)
                    self.g.anchor_set(head, anchor[0], anchor[1])
                body.append(symbol)
            # T -> F M1 T' {T.val = T'.val}
            root = Production(rule.head, body)
            root.precedence = rule.precedence
            action = {}
            stack_pos = len(body)
            # 产生式最右边的语法动作
            keys = list(filter(lambda k: k >= len(rule), rule.action.keys()))
            keys.sort()
            # print('keys', keys)
            for key in keys:
                assert key >= len(rule)
                for act in rule.action[key]:
                    if stack_pos not in action:
                        action[stack_pos] = []
                    action[stack_pos].append((act[0], stack_pos))
            if action:
                root.action = action
            # 先将原来的产生式加入到 rules, 再将所有标记符 M 的产生式加入到 rules
            rules.append(root)
            anchors.append(anchor)
            for child in children:
                rules.append(child)
                anchors.append(anchor)
                child.parent = root
        self.g.production.clear()
        for pos, rule in enumerate(rules):
            self.g.append(rule)
            anchor = anchors[pos]
            self.g.anchor_set(rule, anchor[0], anchor[1])
        self.g.update()
        return 0

    def set_to_text (self, s):
        t = []
        if len(s) == 0:
            return '{ }'
        for n in s:
            t.append((n == '') and '<empty>' or n)
        return '{ %s }'%(', '.join(t),)

    def print_epsilon (self):
        rows = []
        rows.append(['Symbol', 'Is Epsilon', 'Has Epsilon'])
        for info in self.info.values():
            eis = info.is_epsilon and 1 or 0
            ehas = info.has_epsilon and 1 or 0
            rows.append([info.name, eis, ehas])
        text = cstring.tabulify(rows, 1)
        print(text)
        print()
        return 0

    def print_first (self):
        rows = []
        rows.append(['Symbol X', 'First[X]', 'Follow[X]'])
        for name in self.nonterminal:
            t1 = self.set_to_text(self.FIRST[name])
            t2 = self.set_to_text(self.FOLLOW[name])
            rows.append([name, t1, t2])
        text = cstring.tabulify(rows, 1)
        print(text)
        print()
        return rows


#----------------------------------------------------------------------
# RulePtr: Universal LR Item for LR(0), SLR, LR(1), and LALR
# ptr: pointer. suchs as: S->·bBB, · is pointer
# "<S : * bBB>" is RulePtr name
#----------------------------------------------------------------------
class RulePtr (object):

    def __init__ (self, production: Production, index: int, lookahead = None):
        assert index <= len(production)
        self.rule = production
        self.index = index
        self.lookahead = lookahead    # None or a string, follow subset(production.head)
        self.__name = None
        self.__hash = None
        self.__text = None

    def __len__ (self) -> int:
        return len(self.rule)

    def __contains__ (self, symbol) -> bool:
        return (symbol in self.rule)

    def __getitem__ (self, key) -> Symbol:
        return self.rule[key]

    @property
    def next (self) -> Symbol:
        if self.index >= len(self.rule.body):
            return None
        return self.rule.body[self.index]

    # generate new RulePtr object if advance
    def advance (self):
        if self.index >= len(self.rule.body):
            return None
        return RulePtr(self.rule, self.index + 1, self.lookahead)

    # dot is at rightmost production
    @property
    def satisfied (self) -> bool:
        return (self.index >= len(self.rule))

    def __str__ (self) -> str:
        if self.__text is not None:
            return self.__text
        before = [ x.name for x in self.rule.body[:self.index] ]
        after = [ x.name for x in self.rule.body[self.index:] ]
        t = '%s * %s'%(' '.join(before), ' '.join(after))
        if self.lookahead is not None:
            t += ', ' + str(self.lookahead)
        self.__text = '<%s : %s>'%(self.rule.head, t)
        return self.__text

    def __repr__ (self) -> str:
        return '%s(%r, %r)'%(type(self).__name__, self.rule, self.index)

    def __copy__ (self):
        obj = RulePtr(self.rule, self.index, self.lookahead)
        obj.__name = self.name
        obj.__hash = self.hash
        return obj

    def __deepcopy__ (self, memo):
        return self.__copy__()

    def __hash__ (self) -> int:
        if self.__hash is None:
            self.__hash = hash((hash(self.rule), self.index, self.lookahead))
        return self.__hash

    def __eq__ (self, rp) -> bool:
        assert isinstance(rp, RulePtr)
        if (self.index == rp.index) and (self.lookahead == rp.lookahead):
            return (self.rule == rp.rule)
        return False

    def __ne__ (self, rp) -> bool:
        return (not self == rp)

    def __ge__ (self, rp) -> bool:
        if self.index > rp.index:
            return True
        elif self.index < rp.index:
            return False
        if (self.lookahead is not None) or (rp.lookahead is not None):
            s1 = repr(self.lookahead)
            s2 = repr(rp.lookahead)
            if s1 > s2:
                return True
            if s1 < s2:
                return False
        return self.rule >= rp.rule

    def __gt__ (self, rp) -> bool:
        if self.index > rp.index:
            return True
        elif self.index < rp.index:
            return False
        if (self.lookahead is not None) or (rp.lookahead is not None):
            s1 = repr(self.lookahead)
            s2 = repr(rp.lookahead)
            if s1 > s2:
                return True
            if s1 < s2:
                return False
        return self.rule > rp.rule

    def __le__ (self, rp) -> bool:
        return (not (self > rp))

    def __lt__ (self, rp) -> bool:
        return (not (self >= rp))

    @property
    def name (self) -> str:
        if self.__name is None:
            self.__name = self.__str__()
        return self.__name

    # vector which follow dot at production
    # example:
    #   E -> b * BB
    #   return [B, B]
    def after_list (self, inc = 0) -> list:
        return [n for n in self.rule.body[self.index + inc:]]


#----------------------------------------------------------------------
# Universal ItemSet for LR(0), SLR, LR(1)
#----------------------------------------------------------------------
class LRItemSet (object):

    '''
    圆点不在产生式右部最左边的项目称为内核项，唯一的例外是 S' → • S。因此用 GOTO(I, X)转换函数得到的 J 为转向后状态所含项目集的内核项
    使用闭包函数(CLOSURE)和转向函数(GOTO(I, X)) 构造文法 G' 的 LR 的项目集规范族
    '''
    def __init__ (self, kernel_source: list[RulePtr]):
        # 内核项
        self.kernel = LRItemSet.create_kernel(kernel_source)
        self.closure = []
        # 标记非内核项的位置
        self.checked = {}
        self.__hash = None
        self.__name = None
        self.uuid = -1

    @staticmethod
    def create_kernel (kernel_source):
        klist = [n for n in kernel_source]
        klist.sort()
        return tuple(klist)

    # 内核项作为状态名即可，因为项集的内核项相同，非内核项一定也相同，都是又传播和自发生成而来的
    @staticmethod
    def create_name (kernel_source):
        knl = LRItemSet.create_kernel(kernel_source)
        text = ', '.join([str(n) for n in knl])
        # 919393 is prime
        # knl must be tuple instead of list
        # hash tuple is correct, hash list is incorrect
        h = hash(knl) % 919393
        return 'C' + str(h) + '(' + text + ')'

    def __len__ (self):
        return len(self.closure)

    def __getitem__ (self, key):
        if isinstance(key, str):
            index = self.checked[key]
            return self.closure[index]
        return self.closure[key]

    def __contains__ (self, key):
        if isinstance(key, int):
            return ((key >= 0) and (key < len(self.closure)))
        elif isinstance(key, RulePtr):
            return (key.name in self.checked)
        elif isinstance(key, str):
            return (key in self.checked)
        return False

    def clear (self):
        self.closure.clear()
        self.checked.clear()
        return 0

    def __hash__ (self):
        if self.__hash is None:
            self.__hash = hash(self.kernel)
        return self.__hash

    def __eq__ (self, obj):
        assert isinstance(obj, LRItemSet)
        if hash(self) != hash(obj):
            return False
        return (self.kernel == obj.kernel)

    def __ne__ (self, obj):
        return (not (self == obj))

    @property
    def name (self):
        if self.__name is None:
            self.__name = LRItemSet.create_name(self.kernel)
        return self.__name

    def append (self, item: RulePtr):
        if item.name in self.checked:
            LOG_ERROR('duplicated item:', item)
            assert item.name not in self.checked
            return -1
        self.checked[item.name] = len(self.closure)
        self.closure.append(item)
        return 0

    def __iter__ (self):
        return self.closure.__iter__()

    # find all symbols which follow dot
    def find_expecting_symbol (self):
        output = []
        checked = set([])
        # rp: rule pointer
        for rp in self.closure:
            if rp.next is None:
                continue
            if rp.next.name not in checked:
                checked.add(rp.next.name)
                output.append(rp.next)
        return output

    def print (self):
        rows = []
        print('STATE(%d): %s'%(self.uuid, self.name))
        for i, rp in enumerate(self.closure):
            # (K) is kernel, (C) is closure
            t = (i < len(self.kernel)) and '(K)' or '(C)'
            rows.append([' ', i, str(rp), '  ', t])
        text = cstring.tabulify(rows, 0)
        print(text)
        print()
        return 0


#----------------------------------------------------------------------
# ActionName
#----------------------------------------------------------------------
class ActionName (IntEnum):
    SHIFT = 0
    REDUCE = 1
    ACCEPT = 2
    ERROR = 3


#----------------------------------------------------------------------
# Action: include action and goto
#----------------------------------------------------------------------
class Action (object):

    # (name: Action.name, target: NextState.uuid | Reduce Production.index, rule: NowProduction)
    def __init__ (self, name: int, target: int, rule: Production = None):
        self.name = name
        self.target = target
        self.rule = rule

    def __eq__ (self, obj):
        assert isinstance(obj, Action)
        return (self.name == obj.name and self.target == obj.target)

    def __ne__ (self, obj):
        return (not (self == obj))

    def __hash__ (self):
        return hash((self.name, self.target))

    def __ge__ (self, obj):
        return ((self.name, self.target) >= (obj.name, obj.target))

    def __gt__ (self, obj):
        return ((self.name, self.target) > (obj.name, obj.target))

    def __lt__ (self, obj):
        return (not (self > obj))

    def __le__ (self, obj):
        return (not (self >= obj))

    def __str__ (self):
        if self.name == ActionName.ACCEPT:
            return 'acc'
        if self.name == ActionName.ERROR:
            return 'err'
        name = ActionName(self.name).name[:1]
        if self.name == ActionName.REDUCE:
            return name + '/' + str(self.target) + '(%s)'%self.rule
        return name + '/' + str(self.target)

    def __repr__ (self):
        return '%s(%r, %r)'%(type(self).__name__, self.mode, self.target)


#----------------------------------------------------------------------
# LRTable
#----------------------------------------------------------------------
'''
LR(1) Table Example

Production:
    0, S' -> S
    1, S  -> L = R
    2, S  -> R
    3, L  -> * R
    4, L  -> id
    5, R  -> L

LRTable:
| state |           ACTION              |     GOTO      |
|       |   *       id      =       $   |   S   L   R   |
|-------|-------------------------------|---------------|
|   0   |   s4      s5                  |   1   2   3   |
|   1   |                          acc  |               |
|   2   |                   s6      r5  |               |
|   3   |                           r2  |               |
|   4   |   s4      s5                  |       8   7   |
|   5   |                   r4      r4  |               |
|   6   |   s11     s12                 |       10  9   |
|   7   |                   r3      r3  |               |
|   8   |                   r5      r5  |               |
|   9   |                           r1  |               |
|   10  |                           r5  |               |
|   11  |   s11     s12                 |       10  13  |
|   12  |                           r4  |               |
|   13  |                           r3  |               |

s: shift,   r: reduce,  acc: accept
si: shift i state
ri: reduce i production
i: shift i state
where i is 0,1,3...N

tab[0]["id"] = [Action(Action.Shift, 5)]
tab[9]["$"] = [Action(Action.Reduce, 1)]
tab[11]["L"] = [Action(Action.Shift, 10)]
'''
class LRTable (object):

    def __init__ (self, head:list[Symbol]):
        self.head = self.__build_head(head)     # all non-terminals and terminals
        self.rows = []
        self.mode = 0   # mode 0 is set, mode 1 is list

    def __build_head (self, head):
        terminal = []
        nonterminal = []
        for symbol in head:
            if symbol.term:
                if symbol.name != '$':
                    terminal.append(symbol)
            else:
                if symbol.name != 'S^':
                    nonterminal.append(symbol)
        terminal.sort()
        terminal.append(EOF)
        nonterminal.sort()
        # nonterminal.insert(0, Symbol('S^', False))
        output = terminal + nonterminal
        return tuple(output)

    def __len__ (self):
        return len(self.rows)

    def __getitem__ (self, row):
        return self.rows[row]

    def __contains__ (self, row):
        return ((row >= 0) and (row < len(self.rows)))

    def __iter__ (self):
        return self.rows.__iter__()

    def clear (self):
        self.rows.clear()
        return 0

    def get (self, row, col):
        if row not in self.rows:
            return None
        return self.rows[row].get(col, None)

    def set (self, row, col, data):
        if isinstance(col, Symbol):
            col = col.name
        if row >= len(self.rows):
            while row >= len(self.rows):
                self.rows.append({})
        rr = self.rows[row]
        if self.mode == 0:
            rr[col] = set([data])
        else:
            rr[col] = [data]
        return 0

    # (row:State.uuid, col:Symbol.name, data:Action)
    def add (self, row:int, col:str, data:Action):
        if isinstance(col, Symbol):
            col = col.name
        if row >= len(self.rows):
            while row >= len(self.rows):
                self.rows.append({})
        rr = self.rows[row]
        if self.mode == 0:
            if col not in rr:
                rr[col] = set([])
            rr[col].add(data)
        else:
            if col not in rr:
                rr[col] = []
            rr[col].append(data)
        return 0

    def print (self):
        rows = []
        head = ['STATE'] + [str(n) for n in self.head]
        rows.append(head)
        for i, row in enumerate(self.rows):
            body = [str(i)]
            for n in self.head:
                col = n.name
                if col not in row:
                    body.append('')
                else:
                    p = row[col]
                    text = ','.join([str(x) for x in p])
                    body.append(text)
            rows.append(body)
        text = cstring.tabulify(rows, 1)
        print(text)
        return rows


#----------------------------------------------------------------------
# Node
#----------------------------------------------------------------------
class Node (object):
    
    def __init__ (self, name, child):
        self.name = name
        self.child = [n for n in child]

    def __repr__ (self):
        clsname = type(self).__name__
        return '%s(%r, %r)'%(clsname, self.name, self.child)

    def __str__ (self):
        return self.__repr__()

    def print (self, prefix = ''):
        print(prefix, end = '')
        print(self.name)
        for child in self.child:
            if isinstance(child, Node):
                child.print(prefix + '| ')
            elif isinstance(child, Symbol):
                print(prefix + '| ' + str(child))
            else:
                print(prefix + '| ' + str(child))
        return 0


#----------------------------------------------------------------------
# LR(1) Analyzer
#----------------------------------------------------------------------
class LR1Analyzer (object):

    def __init__ (self, g: Grammar):
        self.g = g
        self.ga = GrammarAnalyzer(self.g)
        self.verbose = 2
        self.state = {}         # state by uuid
        self.names = {}         # state by name
        self.link = {}          # state switch
        self.backlink = {}      #
        self.tab = None         # LR table
        self.pending = collections.deque()  # BFS state deque

    def process (self):
        self.clear()
        self.ga.process()
        error = self.ga.check_grammar()
        if error > 0:
            return 1
        if len(self.g) == 0:
            return 2
        if 'S^' not in self.g.symbol:
            self.g.augment()
        hr = self.__build_states()
        if hr != 0:
            return 3
        hr = self.build_table()
        if hr != 0:
            return 4
        return 0

    def __len__ (self):
        return len(self.state)

    def __contains__ (self, key):
        if isinstance(key, LRItemSet):
            return (key.name in self.names)
        elif isinstance(key, str):
            return (key in self.names)
        elif not hasattr(key, '__iter__'):
            raise TypeError('invalid type')
        name = LRItemSet.create_name(key)
        return (name in self.names)

    def __getitem__ (self, key):
        if isinstance(key, int):
            return self.state[key]
        elif isinstance(key, str):
            return self.names[key]
        elif isinstance(key, LRItemSet):
            return self.names[key.name]
        elif not hasattr(key, '__iter__'):
            raise TypeError('invalid type')
        name = LRItemSet.create_name(key)
        return self.names[name]

    def __iter__ (self):
        return self.state.__iter__()

    def append (self, state:LRItemSet):
        if state in self:
            raise KeyError('conflict key')
        state.uuid = len(self.state)
        self.state[state.uuid] = state
        self.names[state.name] = state
        self.pending.append(state)
        return 0

    def clear (self):
        self.state.clear()
        self.names.clear()
        self.link.clear()
        self.backlink.clear()
        self.pending.clear()
        return 0

    """
    # https://mmmhj2.github.io/%E7%BC%96%E8%AF%91%E5%8E%9F%E7%90%86/2023/01/11/syntax-analysis-bottomup-CLR.html
    # https://www.cnblogs.com/cyjb/p/ParserLALR.html
    # 计算 LR1 的 CLOSURE(I)
    def CLOSURE(I):
        J = I
        changed = True
        # 直到没有新的 [B -> . γ, b] 项加入到 J
        while changed:
            changed = False
            # 对闭包中每一个项 [A -> α . B β, a] ...
            for item in J:
                # 对每个产生式 B -> γ ...
                for prod in productions:
                    if not item.next == prod.head:
                        continue
                    # item.next 是非终结符
                    # 构造 βa
                    # vector = β + a
                    vector = item.after_dot + [item.lookahead]
                    # 对 FIRST(βa) 中所有终结符号 b, 即为 B -> . γ 的向前符号...
                    for b in FIRST(vector):
                        next_pointer = RulePointer(production=prod, index=0, lookahead=b)
                        if not next_pointer in J:
                            # 把项 [B -> . γ, b] 加入闭包中
                            J.append(next_pointer)
                            changed = True
        return J
        # 为什么这里 B -> . γ 的向前符号在 FIRST(βa) 里？假设我们即将根据项 [A -> α . B β, a] 归约, 那么显然我们已经看到了输入 ...α B β a
        # (这里 a 是向前看符号，显然要求下一个输入是 a 时才能归约），那我们再向前倒推到按照 B -> γ 归约前，就会有 ...α B β a = ...α γ β a,
        # 就可以看到只有 γ 后跟 βa 时, 才有可能按照 B -> γ 归约，即 B -> γ 的向前看符号在 FIRST(βa) 之中。
    """
    # 扩充 LRItemSet，不产生新的 LRItemSet
    def closure (self, cc:LRItemSet) -> LRItemSet:
        cc.clear()
        for n in cc.kernel:
            if n.name not in cc:
                cc.append(n)
        if 1:
            LOG_DEBUG('')
            LOG_DEBUG('-' * 72)
            LOG_DEBUG('CLOSURE init')
        top = 0
        '''
        while 1:
            changes = 0
            ....
            if not changes:
                break

        similarly:
            do while
        '''
        while 1:
            changes = 0
            limit = len(cc.closure)
            # for A in cc.closure:
            while top < limit:
                A: RulePtr = cc.closure[top]
                top += 1
                B: Symbol = A.next
                if B is None:
                    continue
                if B.term:
                    continue
                # next A is non-terminal
                if B.name not in self.g.rule:
                    LOG_ERROR('no production rules for symbol %s'%B.name)
                    raise GrammarError('no production rules for symbol %s'%B.name)
                if 1:
                    LOG_DEBUG('CLOSURE iteration') 
                    LOG_DEBUG(f'A={A} B={B}')
                after = A.after_list(1)
                if A.lookahead is not None:
                    after.append(A.lookahead)
                first = self.ga.vector_first_set(after)
                first = [load_symbol(n) for n in first]
                for f in first:
                    if f.name != '':
                        f.term = True
                if 1:
                    LOG_DEBUG('after:', after)
                    LOG_DEBUG('first:', first)
                for rule in self.g.rule[B.name]:
                    for term in first:
                        rp = RulePtr(rule, 0, term)
                        if rp.name not in cc:
                            cc.append(rp)
                            changes += 1
            if changes == 0:
                break
        return cc

    """
    # 计算 GOTO(I,X)
    def GOTO(I:ItemSet, X:Symbol):
        goto = empty_set()
        # for 每个项 [A -> α . X β, a]
        for item in I:
            # 注意点在产生式末尾的情况
            if item.next == X:
                # 把项 [A -> α X . β, a] 加入项集中
                next_pointer = RulePointer(production=item=item.prod, index=item.index+1, lookahead=item.lookahead)
                goto.append(next_pointer)
        goto = CLOSURE(goto)
        return goto
    """
    def goto (self, cc:LRItemSet, X:Symbol) -> LRItemSet:
        kernel = []
        for rp in cc:
            if rp.next is None:
                continue
            if rp.next.name != X.name:
                continue
            # if next is Symbol X
            # np: next RulePtr
            np = rp.advance()
            if np is None:
                continue
            kernel.append(np)
        if not kernel:
            return None
        # 内核项
        nc = LRItemSet(kernel)
        # 对内核项求 closure，传播和自发生成非内核项，项集中加入非内核项
        return self.closure(nc)

    # 只产生内核项，不求 closure
    def __try_goto (self, cc:LRItemSet, X:Symbol):
        kernel = []
        for rp in cc:
            if rp.next is None:
                continue
            if rp.next.name != X.name:
                continue
            np = rp.advance()
            if np is None:
                continue
            kernel.append(np)
        if not kernel:
            return None
        return kernel

    def __build_states (self):
        self.clear()
        g = self.g
        assert g.start is not None
        assert g.start.name == 'S^'
        assert g.start.name in g.rule
        assert len(g.rule[g.start.name]) == 1
        rule = self.g.rule[g.start.name][0]
        rp = RulePtr(rule, 0, EOF)
        state = LRItemSet([rp])
        self.closure(state)
        self.append(state)
        while 1:
            if 0:
                changes = 0
                for state in list(self.state.values()):
                    changes += self.__update_state(state)
                if not changes:
                    break
            else:
                # BFS
                if len(self.pending) == 0:
                    break
                state = self.pending.popleft()
                self.__update_state(state)
        return 0

    def __update_state (self, cc:LRItemSet):
        changes = 0
        for symbol in cc.find_expecting_symbol():
            # print('expecting', symbol)
            kernel_list = self.__try_goto(cc, symbol)
            if not kernel_list:
                continue
            name = LRItemSet.create_name(kernel_list)
            if name in self:
                ns = self.names[name]
                self.__create_link(cc, ns, symbol)
                continue
            LOG_VERBOSE('create state %d'%len(self.state))
            ns = LRItemSet(kernel_list)
            self.closure(ns)
            self.append(ns)
            self.__create_link(cc, ns, symbol)
            # print(ns.name)
            changes += 1
        return changes

    # 状态转移表 link[<now state>][<go symbol>] = <next state>
    #           backlink[<next state>][<back symbol>] = <now state>
    def __create_link (self, c1:LRItemSet, c2:LRItemSet, ss:Symbol):
        assert c1 is not None
        assert c2 is not None
        assert c1.uuid >= 0
        assert c2.uuid >= 0
        if c1.uuid not in self.link:
            self.link[c1.uuid] = {}
        if ss.name not in self.link[c1.uuid]:
            self.link[c1.uuid][ss.name] = c2.uuid
        else:
            if self.link[c1.uuid][ss.name] != c2.uuid:
                LOG_ERROR('conflict states')
        if c2.uuid not in self.backlink:
            self.backlink[c2.uuid] = {}
        if ss.name not in self.backlink[c2.uuid]:
            self.backlink[c2.uuid][ss.name] = c1.uuid
        return 0

    def __build_table (self):
        heading = [n for n in self.g.symbol.values()]
        self.tab = LRTable(heading)
        tab: LRTable = self.tab
        # tab.mode = 1
        if 0:
            import pprint
            pprint.pprint(self.link)
        for state in self.state.values():
            uuid = state.uuid
            link = self.link.get(uuid, None)
            LOG_VERBOSE(f'build table for I{state.uuid}')
            # LOG_VERBOSE(
            for rp in state.closure:
                rp: RulePtr = rp
                # dot is at rightmost production
                if rp.satisfied:
                    LOG_VERBOSE("  satisfied:", rp)
                    if rp.rule.head.name == 'S^':
                        if len(rp.rule.body) == 1:
                            # 增广产生式的 body 只有一个, S^ -> S
                            action = Action(ActionName.ACCEPT, 0)
                            action.rule = rp.rule
                            tab.add(uuid, rp.lookahead.name, action)
                        else:
                            LOG_ERROR('error accept:', rp)
                    else:
                        action = Action(ActionName.REDUCE, rp.rule.index)
                        action.rule = rp.rule
                        tab.add(uuid, rp.lookahead.name, action)
                # include ACTION and GOTO table
                # ACTION[i, a] = sj ; current state i, terminal a, shift s, next state j
                # GOTO[i, a] = j ; current state i, non-terminal a, next state j
                elif rp.next.name in link:
                    target = link[rp.next.name]
                    action = Action(ActionName.SHIFT, target, rp.rule)
                    tab.add(uuid, rp.next.name, action)
                else:
                    LOG_ERROR('error link')
        return 0

    def build_LR1_table (self) -> LRTable:
        self.__build_table()
        return self.tab

    def build_table (self) -> LRTable:
        return self.__build_table()


#----------------------------------------------------------------------
# LALRItemSet
#----------------------------------------------------------------------
'''
LALR: lookahead-LR
构造 LALR(1) 项目有两种思路。一种是：先构造 LR(1) 项目，再合并同心项目；另一种是：先构造 LR(0) 项目，再为其配上搜索符。介绍第二种方法:

搜索符生成有两种方法。一是，自己生成。二是，上一项目集传播获得的。项目集之间传播搜索符遇到的问题是：若多个项目集可以直接转移到一个项目集 I 上，那么每当 I 接收到，这些项目集传播过来的新的搜索符时，I 就得重新再往下传播自己新的搜索符。
考虑到这一点可以使用压栈的方式，将可以传播的项目压栈存好，将栈顶弹出用于传播，在传播过程中同时压入新的可传播项目。直到最后栈为空，即没有项目可以传播为止。

Production 相同、圆点位置相同而 lookahead 不同的两个状态，在 LALR (1) 眼里是相同的，在 LR (1) 眼里是不同的。
因此 lookahead 是一个集合。
'''
class LALRItemSet (LRItemSet):

    def __init__ (self, kernel_source):
        super(LALRItemSet, self).__init__(kernel_source)
        self.lookahead = [set([]) for n in range(len(self.kernel))] # set
        self.dirty = False  # dirty is True if ItemSet modified

    def shrink (self):
        while len(self.closure) > len(self.kernel):
            self.closure.pop()
        return 0

    def print (self):
        rows = []
        print('STATE(%d): %s'%(self.uuid, self.name))
        for i, rp in enumerate(self.closure):
            if i < len(self.kernel):
                p = ' ' .join([str(n) for n in self.lookahead[i]])
                p = '{' + p + '}'
                t = '(K)'   # kernel
            else:
                p = ''
                t = '(C)'   # closure
            rows.append([' ', i, str(rp), p, '  ', t])
        text = cstring.tabulify(rows, 0)
        print(text)
        print()
        return 0


#----------------------------------------------------------------------
# LALR Analyzer
#----------------------------------------------------------------------
'''
G:
    S -> L = R | R
    L -> * R | id
    R -> L

G':
    S' -> S
    S -> L = R
    S -> R
    L -> * R
    L -> id
    R -> L

I0:
    S' -> . S       (K)
    S -> . L = R    (C)
    S -> . R        (C)
    L -> . * R      (C)
    L -> . id       (C)
    R -> . L        (C)

I1:
    S' -> S .       (K)

I2:
    S' -> L . = R   (K)
    R -> L .        (K)

I3:
    S -> R .        (K)

I4:
    L -> * . R      (K)
    R -> . L        (C)
    L -> . * R      (C)
    L -> . id       (C)

I5:
    L -> id .       (K)

I6:
    S -> L = . R    (K)
    R -> . L        (C)
    L -> . * R      (C)
    L -> . id       (C)

I7:
    L -> * R .      (K)

I8:
    R -> L .        (K)

I9:
    S -> L = R .    (K)

首先删除 LR0 项集中的非内核项, 再求 closure([S' -> . S, #]):
    S' -> . S       , #     (K)
    S -> . L = R    , #     (C)
    S -> . R        , #     (C)
    L -> . * R      , =/#   (C)
    L -> . id       , =/#   (C)
    R -> . L        , #     (C)
# 是传播向前看符号，= 是自发生成的向前看符号, 其中有 2 项有自发生成的向前看符号
goto([S' -> . S, #], S)     = [S' -> S ., #]    , [S' -> S .] in I0
goto([S -> . L = R, #], L)  = [S -> L . = R, #] , [S -> L . = R] in I2
goto([S -> . R, #], R)      = [S -> R . , #]    , [S -> R .] in I3
goto([L -> . * R, #], *)    = [L -> * . R, #]   , [L -> * . R] in I4
goto([L -> . id, #], id)    = [L -> id ., #]    , [L -> id .] in I5
goto([R -> . L, #], L)      = [R -> L ., #]     , [R -> L .] in I2

goto([L -> . * R, =], *)    = [L -> * . R, =]   , [L -> * . R] in I4
goto([L -> . id, =], id)    = [L -> id ., =]    , [L -> id .] in I5

现在初始化表格，由于这个表格一开始只包含自发生成的向前看符号，因此表格初始化为：
| LR0 项集 |        内核项      | 向前看符号, 初始值 |  已经传播过 或者 圆点到终点   |
|   I0     | S' -> . S         |        $          |           传播              |
|   I1     | S' -> S .         |                   |            v               |
|   I2     | S  -> L . = R     |                   |                            |
|          | R  -> L .         |                   |            v               |
|   I3     | S  -> R .         |                   |            v               |
|   I4     | L  -> * . R       |        =          |                            |
|   I5     | L  -> id .        |        =          |            v               |
|   I6     | S  -> L = . R     |                   |                            |
|   I7     | L  -> * R .       |                   |            v               |
|   I8     | R  -> L .         |                   |            v               |
|   I9     | S  -> L = R .     |                   |            v               |

只计算 = 的传播, 因此计算 I4 的 closure([L -> * . R, #]) 和 I5 的 closure([L -> id ., #]), 由于 I5 的 [L -> id ., #] 圆点达到终点, 无需其计算闭包。
    L -> * · R  , #     (K)
    R -> · L    , #     (C)
    L -> · * R  , #     (C)
    L -> · id   , #     (C)

goto([L -> * . R, #], R)    = [L -> * R ., #]   , [L -> * R .] in I7
goto([R -> . L, #], L)      = [R -> L ., #]     , [R -> L .] in I8
goto([L -> . * R, #], R)    = [L -> * . R, #]   , [L -> * . R] in I4
goto([L -> . id, #], id)    = [L -> id ., #]    , [L -> id .] in I5

= 传播到 I7 的 [L -> * R .], I8 的 [R -> L .], I4 的 [L -> * . R], I5 的 [L -> id .]
因此经过第一趟传播后表格变为：
| LR0 项集 |        内核项      | 向前看符号, 初始值 |  第一趟 |  已经传播过 或者 圆点到终点   |
|   I0     | S' -> . S         |        $          |    $   |              1              |
|   I1     | S' -> S .         |                   |    $   |              v              |
|   I2     | S  -> L . = R     |                   |    $   |                             |
|          | R  -> L .         |                   |    $   |              v              |
|   I3     | S  -> R .         |                   |    $   |              v              |
|   I4     | L  -> * . R       |        =          |   =/$  |            传播              |
|   I5     | L  -> id .        |        =          |   =/$  |              v              |
|   I6     | S  -> L = . R     |                   |        |                             |
|   I7     | L  -> * R .       |                   |    =   |              v              |
|   I8     | R  -> L .         |                   |    =   |              v              |
|   I9     | S  -> L = R .     |                   |        |              v              |

开始进行第二趟传播, I2 的 S -> L . = R 需要计算闭包。计算 closure([S -> L . = R, #]) 得到:
    S -> L · = R   , #      (K)
goto([S -> L . = R, #], =)    = [S -> L = . R, #]   , [S -> L = . R] in I6

因此经过第二趟传播后表格变为：
| LR0 项集 |        内核项      | 向前看符号, 初始值 |  第一趟 |  第二趟 |  已经传播过 或者 圆点到终点   |
|   I0     | S' -> . S         |        $          |    $   |    $    |              1              |
|   I1     | S' -> S .         |                   |    $   |    $    |              v              |
|   I2     | S  -> L . = R     |                   |    $   |    $    |             传播             |
|          | R  -> L .         |                   |    $   |    $    |              v              |
|   I3     | S  -> R .         |                   |    $   |    $    |              v              |
|   I4     | L  -> * . R       |        =          |   =/$  |   =/$   |              2              |
|   I5     | L  -> id .        |        =          |   =/$  |   =/$   |              v              |
|   I6     | S  -> L = . R     |                   |        |    $    |                             |
|   I7     | L  -> * R .       |                   |    =   |   =/$   |              v              |
|   I8     | R  -> L .         |                   |    =   |   =/$   |              v              |
|   I9     | S  -> L = R .     |                   |        |         |              v              |

开始进行第三趟传播, I6 的 S -> L = . R 需要计算闭包。计算 closure([S -> L = . R, #]) 得到:
    S -> L = . R   , #      (K)
    R -> . L       , #      (C)
    L -> . * R     , #      (C)
    L -> . id      , #      (C)
goto([S -> L = . R, #], R)    = [S -> L = R ., #]   , [S -> L = R .] in I9
goto([R -> . L, #], L)        = [R -> L ., #]       , [R -> L .] in I8
goto([L -> . * R, #], *)      = [R -> * . R, #]     , [L -> * . R] in I4
goto([L -> . id, #], id)      = [L -> id ., #]      , [L -> id .] in I5

因此经过第二趟传播后表格变为：
| LR0 项集 |        内核项      | 向前看符号, 初始值 |  第一趟 |  第二趟 |  第三趟 |  已经传播过 或者 圆点到终点   |
|   I0     | S' -> . S         |        $          |    $   |    $    |    $   |              1              |
|   I1     | S' -> S .         |                   |    $   |    $    |    $   |              v              |
|   I2     | S  -> L . = R     |                   |    $   |    $    |    $   |              3              |
|          | R  -> L .         |                   |    $   |    $    |    $   |              v              |
|   I3     | S  -> R .         |                   |    $   |    $    |    $   |              v              |
|   I4     | L  -> * . R       |        =          |   =/$  |   =/$   |   =/$  |              2              |
|   I5     | L  -> id .        |        =          |   =/$  |   =/$   |   =/$  |              v              |
|   I6     | S  -> L = . R     |                   |        |    $    |    $   |             传播             |
|   I7     | L  -> * R .       |                   |    =   |   =/$   |   =/$  |              v              |
|   I8     | R  -> L .         |                   |    =   |   =/$   |   =/$  |              v              |
|   I9     | S  -> L = R .     |                   |        |         |    $   |              v              |
结束, 将最后一次传播的向前看符号加入到 LR(0) 项集中, 得到 LALR 项集。

'''
class LALRAnalyzer (object):

    def __init__ (self, g: Grammar):
        self.g: Grammar = g
        self.ga: GrammarAnalyzer = GrammarAnalyzer(self.g)
        self.la: LR1Analyzer = LR1Analyzer(self.g)
        self.state = {}         # state by uuid
        self.names = {}         # state by name
        self.link = {}          # state switch
        self.backlink = {}      #
        self.route = {}
        self.pending = collections.deque()
        self.dirty = set([])
        self.cache = {}

    def __len__ (self):
        return len(self.state)

    def __contains__ (self, key):
        if isinstance(key, LALRItemSet):
            return (key.name in self.names)
        elif isinstance(key, str):
            return (key in self.names)
        elif not hasattr(key, '__iter__'):
            raise TypeError('invalid type')
        name = LRItemSet.create_name(key)
        return (name in self.names)

    def __getitem__ (self, key):
        if isinstance(key, int):
            return self.state[key]
        elif isinstance(key, str):
            return self.names[key]
        elif isinstance(key, LRItemSet):
            return self.names[key.name]
        elif isinstance(key, LALRItemSet):
            return self.names[key.name]
        elif not hasattr(key, '__iter__'):
            raise TypeError('invalid type')
        name = LRItemSet.create_name(key)
        return self.names[name]

    def __iter__ (self):
        return self.state.__iter__()

    def append (self, state:LALRItemSet):
        if state in self:
            raise KeyError('conflict key')
        state.uuid = len(self.state)
        self.state[state.uuid] = state
        self.names[state.name] = state
        self.pending.append(state)
        return 0

    def clear (self):
        self.state.clear()
        self.names.clear()
        self.link.clear()
        self.backlink.clear()
        self.pending.clear()
        self.route.clear()
        self.cache.clear()
        return 0

    def process (self):
        self.clear()
        self.la.clear()
        self.ga.process()
        self.la.ga = self.ga
        error = self.ga.check_grammar()
        if error > 0:
            return 1
        if len(self.g) == 0:
            return 2
        if 'S^' not in self.g.symbol:
            self.g.augment()
        error = self.__LR0_build_states()
        if error > 0:
            return 3
        error = self.__build_propagate_route()
        if error > 0:
            return 4
        self.__build_lookahead()
        self.__build_LR1_state()
        self.tab = self.la.build_LR1_table()
        return 0

    def _LR0_closure (self, cc:LALRItemSet):
        cc.clear()
        for k in cc.kernel:
            cc.append(k)
        top = 0
        while 1:
            changes = 0
            limit = len(cc)
            while top < limit:
                A: RulePtr = cc.closure[top]
                top += 1
                B = A.next
                if B is None:
                    continue
                if B.term:
                    continue
                # next A is non-terminal
                if B.name not in self.g.rule:
                    LOG_ERROR('no production rules for symbol %s'%B.name)
                for rule in self.g.rule[B.name]:
                    li = RulePtr(rule, 0, None)
                    if li not in cc:
                        cc.append(li)
                        changes += 1
            if not changes:
                break
        return cc

    def _LR0_goto (self, cc:LALRItemSet, X:Symbol):
        kernel = []
        for li in cc:
            if li.next is None:
                continue
            if li.next.name != X.name:
                continue
            np = li.advance()
            if np is None:
                continue
            kernel.append(np)
        if not kernel:
            return None
        nc = LALRItemSet(kernel)
        return self._LR0_closure(nc)

    def __LR0_try_goto (self, cc:LALRItemSet, X:Symbol):
        kernel = []
        for lp in cc:
            if lp.next is None:
                continue
            if lp.next.name != X.name:
                continue
            np = lp.advance()
            if np is None:
                continue
            kernel.append(np)
        if not kernel:
            return None
        return kernel

    def __LR0_build_states (self):
        self.clear()
        g = self.g
        assert g.start is not None
        assert g.start.name == 'S^'
        assert g.start.name in g.rule
        assert len(g.rule[g.start.name]) == 1
        rule = self.g.rule[g.start.name][0]
        lp = RulePtr(rule, 0)
        state = LALRItemSet([lp])   # 实际上是 LR0 项集，构造 LR0 项集不带 lookahead
        self._LR0_closure(state)
        self.append(state)
        while 1:
            # BFS
            if len(self.pending) == 0:
                break
            state = self.pending.popleft()
            self.__LR0_update_state(state)
        return 0

    def __LR0_update_state (self, cc:LALRItemSet):
        changes = 0
        for symbol in cc.find_expecting_symbol():
            # print('expecting', symbol)
            kernel_list = self.__LR0_try_goto(cc, symbol)
            if not kernel_list:
                continue
            name = LRItemSet.create_name(kernel_list)
            if name in self:
                ns = self.names[name]
                self.__create_link(cc, ns, symbol)
                continue
            LOG_VERBOSE('create state %d'%len(self.state))
            ns = LALRItemSet(kernel_list)
            self._LR0_closure(ns)
            self.append(ns)
            self.__create_link(cc, ns, symbol)
            # print(ns.name)
            changes += 1
        return changes

    def __create_link (self, c1:LALRItemSet, c2:LALRItemSet, ss:Symbol):
        assert c1 is not None
        assert c2 is not None
        assert c1.uuid >= 0
        assert c2.uuid >= 0
        if c1.uuid not in self.link:
            self.link[c1.uuid] = {}
        if ss.name not in self.link[c1.uuid]:
            self.link[c1.uuid][ss.name] = c2.uuid
        else:
            if self.link[c1.uuid][ss.name] != c2.uuid:
                LOG_ERROR('conflict states')
        if c2.uuid not in self.backlink:
            self.backlink[c2.uuid] = {}
        if ss.name not in self.backlink[c2.uuid]:
            self.backlink[c2.uuid][ss.name] = c1.uuid
        return 0

    def _LR1_create_closure (self, kernel_list) -> LRItemSet:
        for n in kernel_list:
            if not isinstance(n, RulePtr):
                raise TypeError('kernel_list must be a list of RulePtr')
        cc = LRItemSet(kernel_list)
        self.la.closure(cc)
        return cc

    '''
    LALR 项集是可以直接根据 LR (1) 项集合并而来的，但构造 LR (1) 项集族的时间和空间成本都比较高，更实用的是根据 LR (0) 项集族，通过一个 “传播和自发生成” 过程直接生成向前看符号，高效计算 LALR 项的内核。
        1. 假设项集 I 包含项 [A -> α . β, a], 且 goto(I, X) = J。无论 a 为何值，在 goto(closure([A -> α . β, a]), X) 时得到的结果中总是包含 [B -> γ . δ, b]。那么对于 B -> γ . δ 来说, 向前看符号 b 就是自发生成的。
        2. 其他条件相同，但有 a = b, 且结果中包含 [B -> γ . δ, b] 的原因是项 A -> α . β 有一个向前看符号 b, 那我们就说向前看符号 b 从 I 的项 A -> α . β 传播到了 J 的项 B -> γ . δ 中。需要注意的是，这里的传播关系与特定向前看符号无关，要么所有向前看符号都从一个项传播到另一个项，要么都不传播。

    找到每个 LR (0) 项集中自发生成的向前看符号，和向前看符号的传播过程，就可以为 LR (0) 项添加上正确的向前看符号了。

    首先需要选择一个不在当前文法中的符号 #，由于它不在文法当中，所以不可能被自发生成。如果计算后的向前看符号是否包含 #，说明向前看符号发生了传播，其它向前看符号就是自发生成的。
        1. 为当前项集 I 中的每个项 A -> α . β 计算 J = LR1_closure([A -> α . β, #]), 其中 J 中包含一项 [B -> γ . X δ, a/#]。
        2. 如果 [B -> γ . X δ, a] 在 J 中, 且 a != #, 那么 goto(I, X) 中的项 B -> γ X . δ 的向前看符号 a 时自发生成的。
        3. 如果 [B -> γ . X δ, #] 在 J 中, 那么向前看符号会从 I 中的项 A -> α . β 传播到 goto(I, X) 中的项 B -> γ X . δ 上。

    伪代码：
    令 # 为一个不在当前文法中的符号
    for (LR0 项集 I 的内核项集 K 中的每一个项 A -> α . β) {
        构造产生式 [A -> α . β, #]
        J = LR1_closure([A -> α . β, #])
        for (LR1 项集闭包 J 中的每一项 [B -> γ . X δ, a/#]) {
            [B -> γ . X δ, a] 向前移进一位 B -> γ X . δ, lookahead = None (存在于 goto(I, X) 项集中)
            if ([B -> γ . X δ, a] 在 J 中，且 a != #)
                goto(I, X) 中的项 B -> γ X . δ 的向前看符号 a 时自发生成的。
                即下一项集的 lookahead 是由上一项集生成而来的。
            if ([B -> γ . X δ, #] 在 J 中)
                向前看符号会从 I 中的项 A -> α . β 传播到 goto(I, X) 中的项 B -> γ X . δ 上。
        }
    }

    确定了向前看符号的自发生和传播过程，就可以不断在项集间传播向前看符号直到停止。
        1. 首先，每个项集只包含其自发生成的向前看符号。
        2. 不断扫描每个项集，确定当前项集 I 可以将向前看符号传播到哪些项集，并将 I 的向前看符号添加到被传播到的项集中。
        3. 不断重复步骤 2, 直到每个项集的向前看符号都不再增加。
    '''
    def _LALR_propagate_state (self, state:LALRItemSet) -> int:
        LOG_VERBOSE('propagate', state.uuid)
        for key, kernel in enumerate(state.kernel):
            # 对每个内核项的产生式求 closure
            rule_ptr = RulePtr(kernel.rule, kernel.index, PSHARP)   # PSHARP is #, # is not in grammar
            # 对每个内核项产生式构造带有 lookahead 的 LR1 项集闭包
            closure = self._LR1_create_closure([rule_ptr])
            for _id, rp in enumerate(closure.closure):
                # print('RP', rp)
                expected: Symbol = rp.next
                if rp.satisfied:
                    continue
                elif expected is None:
                    LOG_ERROR('expecting lookahead symbol')
                    assert expected is not None
                assert state.uuid in self.link
                link = self.link[state.uuid]
                assert expected.name in link
                ns: LALRItemSet = self.state[link[expected.name]]   # next state = goto(state, next symbol)
                # print('    ns: uuid', ns.uuid, 'kernel', [str(k) for k in ns.kernel])
                advanced: RulePtr = rp.advance()
                assert advanced
                next_found = -1  # 查找当前项集内核项的产生式移进一位后与下一个项集内核项的产生式的位置
                advanced.lookahead = None
                # print('    advanced: ', advanced)
                for j, nk in enumerate(ns.kernel):  # next kernel
                    # print('nk', nk)
                    if advanced == nk:
                        next_found = j
                        break
                assert next_found >= 0
                if rp.lookahead is None:
                    LOG_ERROR('lookahead should not be None')
                    assert rp.lookahead is not None
                elif rp.lookahead == PSHARP:    # 当前内核项的产生式
                    # 向前看符号发生传播
                    if state.uuid not in self.route:
                        self.route[state.uuid] = {}
                    route = self.route[state.uuid]
                    if key not in route:
                        route[key] = []
                    # 闭包中所有项都有 #, 都会向前传播到其他的项集
                    # rout[current state][kernel production pos at current state] = [(next state, next production pos at next state) ... ]
                    # rout[current state][kernel production pos at current state][next state] = next production pos at next state
                    route[key].append((ns.uuid, next_found))
                    # print('    new route: %s to %s'%(key, (ns.uuid, next_found)))
                else:
                    # 向前看符号自发生成
                    # 下一项集的 lookahead 是由上一项集生成而来的
                    ns.lookahead[next_found].add(rp.lookahead)
        if state.uuid == 0:
            assert len(state.kernel) > 0
            kernel: RulePtr = state.kernel[0]
            assert kernel.rule.head.name == 'S^'
            state.lookahead[0].add(EOF)
        # print()
        return 0

    def __build_propagate_route (self):
        for uuid in self.state:
            state: LALRItemSet = self.state[uuid]   # 不带 lookahead 的 LR0 项集
            state.shrink()      # 删除非内核项
            state.dirty = True
            self._LALR_propagate_state(state)
            # break
        return 0

    def __propagate_state (self, state:LALRItemSet) -> int:
        changes = 0
        # 说明该项集是最后的传播项, 不再指向下一项集。因此最后一次传播结束, 将该项集从栈弹出
        if state.uuid not in self.route:
            state.dirty = False
            if state.uuid in self.dirty:
                self.dirty.remove(state.uuid)
            return 0
        route = self.route[state.uuid]
        for key, kernel in enumerate(state.kernel):
            if key not in route:
                continue
            lookahead = state.lookahead[key]
            for new_uuid, kid in route[key]:
                # next ItemSet uuid, next production pos at next ItemSet
                cc: LALRItemSet = self.state[new_uuid]
                assert kid < len(cc.kernel)
                for symbol in lookahead:
                    # 传播 lookahead: 将当前项集的 lookahead 添加到下一项集的 lookahead
                    if symbol not in cc.lookahead[kid]: # 下一项集的一个产生式的 lookahead 集合
                        cc.lookahead[kid].add(symbol)
                        cc.dirty = True
                        self.dirty.add(cc.uuid)  # 下一项集进栈
                        changes += 1
        state.dirty = False
        if state.uuid in self.dirty:
            self.dirty.remove(state.uuid)   # 当前项集弹栈
        return changes

    def __build_lookahead (self):
        self.dirty.clear()
        # 将所有的项集压入栈
        for uuid in self.state:
            self.dirty.add(uuid)
        while 1:
            if 0:
                changes = 0
                for state in self.state.values():
                    changes += self.__propagate_state(state)
                if changes == 0:
                    break
            else:
                changes = 0
                # list 包裹集合, for 循环时可以对集合进行修改; 直接对集合修改会报错
                for uuid in list(self.dirty):
                    state = self.state[uuid]
                    changes += self.__propagate_state(state)
                if changes == 0:
                    break
        return 0

    def __build_LR1_state (self):
        for state in self.state.values():
            kernel_list = []
            LOG_VERBOSE('building LR1 state', state.uuid)
            for key, kernel in enumerate(state.kernel):
                lookahead = state.lookahead[key]
                for symbol in lookahead:
                    rp = RulePtr(kernel.rule, kernel.index, symbol)
                    kernel_list.append(rp)
            cc = LRItemSet(kernel_list)
            self.la.closure(cc)
            self.la.append(cc)
        self.la.link = self.link
        self.la.backlink = self.backlink
        return 0

#----------------------------------------------------------------------
# LLTable
#----------------------------------------------------------------------
class LLTable (object):

    def __init__ (self):
        self.terminal = set()
        self.rows = {}
        self.nonterminal = set()

    # (row: non-terminal, col: terminal)
    def add (self, row:str, col:str, data:Production):
        if isinstance(row, Symbol):
            row = row.name
        if isinstance(col, Symbol):
            col = col.name
        if row not in self.rows:
            self.rows[row] = {}
        rr = self.rows[row]
        if col not in rr:
            rr[col] = set([])
        rr[col].add(data)
        self.nonterminal.add(row)
        self.terminal.add(col)
        return 0

    def print (self):
        conflict = []
        rows = []
        head = [''] + [str(n) for n in self.terminal]
        rows.append(head)
        for row in self.nonterminal:
            body = [str(row)]
            for col in self.terminal:
                if col not in self.rows[row]:
                    body.append('')
                else:
                    p = self.rows[row][col]
                    text = ' '.join([str(x) for x in p])
                    body.append(text)
                    if len(p) > 1:
                        conflict.append((row, col))
            rows.append(body)
        text = cstring.tabulify(rows, 1)
        print(text)
        if len(conflict) > 0:
            print()
            print("Conflict:")
            for c in conflict:
                print(f"({c[0]}, {c[1]}) -> {' '.join([str(x) for x in self.rows[c[0]][c[1]]])}")
        return 0

#----------------------------------------------------------------------
# LL1Analyzer: modify grammar if exist backtrack or left recursion
#----------------------------------------------------------------------
class LL1Analyzer (object):

    def __init__ (self, g: Grammar):
        self.g = g
        self.ga = GrammarAnalyzer(self.g)
        self.tab = None         # LR table

    def process (self):
        self.__eliminate_left_recursion()
        self.__eliminate_backtrack()
        self.ga = GrammarAnalyzer(self.g)
        self.ga.process()
        error = self.ga.check_grammar()
        if error > 0:
            return 1
        if len(self.g) == 0:
            return 2
        hr = self.__build_table()
        if hr != 0:
            return 3
        return 0

    def __eliminate_direct_left_recursion (self, name, productions:list):
        left_recursive_productions = [copy.copy(production) for production in productions if production.body and production.body[0] == name]
        other_productions = [copy.copy(production) for production in productions if production not in left_recursive_productions]

        if not left_recursive_productions:
            return {name: other_productions}

        new_name = name + '\''
        while new_name in self.g.symbol:
            new_name = new_name + '\''
        for i in range(len(left_recursive_productions)):
            production = left_recursive_productions[i]
            left_recursive_productions[i] = Production(new_name, Vector(list(production.body[1:]) + [Symbol(new_name)]))
        left_recursive_productions.append(Production(new_name, Vector([])))

        for i in range(len(other_productions)):
            production = other_productions[i]
            other_productions[i] = Production(production.head, Vector(list(production.body[:]) + [Symbol(new_name)]))

        return {name: other_productions, new_name: left_recursive_productions}

    def __eliminate_left_recursion (self):
        # dict to list, index can search list
        rule = [(head_name, productions) for head_name, productions in self.g.rule.items()]
        new_rule = {}

        for i in range(len(rule)):
            for j in range(i):
                change = 0
                for k in range(len(rule[i][1])):    # rule[i][1] -> productions
                    if not rule[i][1][k].body:      # rule[i][1][k] -> production
                        continue
                    if rule[i][1][k].body[0] == rule[j][0]:     # rule[j][0] -> head
                        for h in range(len(rule[j][1])):
                            production = rule[j][1][h]
                            new_production = Production(rule[i][0], Vector(production.body[:] + rule[i][1][k].body[1:]))
                            rule[i][1].append(new_production)
                        del rule[i][1][k]
                        # new_rule.pop(rule[j][0])
                        change += 1
                # need remove or not
                if change:
                    for h in range(i, len(rule)):
                        for g in range(len(rule[h][1])):
                            if h == i:
                                if rule[j][0] in rule[h][1][g].body and rule[h][1][g].body and rule[j][0] != rule[h][1][g].body[0]:
                                    change = 0
                            else:
                                if rule[j][0] in rule[h][1][g].body:
                                    change = 0
                if change:
                    new_rule.pop(rule[j][0], None)
            new_rule.update(self.__eliminate_direct_left_recursion(*rule[i]))

        self.g.production = []
        for head_name, productions in new_rule.items():
            self.g.production.extend(productions)
        self.g.update()
        self.g.start = self.g.production[0].head
        # self.g.print()

    def __eliminate_backtrack (self):
        while 1:
            change = 0
            for head_name, productions in self.g.rule.items():
                common_left_factor = []
                for production in productions:
                    if not common_left_factor:
                        # common_prefix, [production.index ...]
                        common_left_factor.append([copy.copy(production.body), [production.index]])
                    else:
                        prefix_len = 0
                        for clf in common_left_factor:
                            prefix = clf[0]
                            for i in range(min(len(prefix), len(production))):
                                if prefix[i] != production.body[i]:
                                    break
                                prefix_len += 1
                            if prefix_len:
                                clf[0] = Vector(prefix[0:prefix_len])
                                clf[1].append(production.index)
                        if not prefix_len:
                            common_left_factor.append([copy.copy(production.body), [production.index]])
                # from pprint import pprint
                # pprint(common_left_factor)
                new_name = head_name + '\''
                for clf in common_left_factor:
                    prefix = clf[0]
                    if len(clf[1]) == 1:
                        continue
                    change += 1
                    while new_name in self.g.symbol:
                        new_name = new_name + '\''
                    new_symbol = Symbol(new_name)
                    for index in clf[1]:
                        production = self.g[index]
                        replace_production = Production(new_symbol, production.body[len(prefix):])
                        self.g.replace(index, replace_production)
                    new_production = Production(head_name, Vector(list(prefix[:]) + [new_symbol]))
                    self.g.append(new_production)
            self.g.update()
            if not change:
                break
        # self.g.print()

    def __build_table (self):
        self.tab = LLTable()
        tab: LLTable = self.tab
        for production in self.g.production:
            head : Symbol = production.head
            body : Vector = production.body
            if not body:
                for col in self.ga.FOLLOW[head.name]:
                    tab.add(head, col, production)
            else:
                for col in self.ga.vector_first_set(body):
                    tab.add(head, col, production)
        # from pprint import pprint
        # pprint(tab.rows)
        self.tab.print()
        return 0

    def build_LL1_table (self) -> LLTable:
        self.__build_table()
        return self.tab

#----------------------------------------------------------------------
# LR0 Analyzer
#----------------------------------------------------------------------
class LR0Analyzer (LR1Analyzer):

    def closure (self, cc:LRItemSet) -> LRItemSet:
        cc.clear()
        for n in cc.kernel:
            if n.name not in cc:
                cc.append(n)
        if 1:
            LOG_DEBUG('')
            LOG_DEBUG('-' * 72)
            LOG_DEBUG('CLOSURE init')
        top = 0
        while 1:
            changes = 0
            limit = len(cc.closure)
            while top < limit:
                A: RulePtr = cc.closure[top]
                top += 1
                B: Symbol = A.next
                if B is None:
                    continue
                if B.term:
                    continue
                if B.name not in self.g.rule:
                    LOG_ERROR('no production rules for symbol %s'%B.name)
                    raise GrammarError('no production rules for symbol %s'%B.name)
                if 1:
                    LOG_DEBUG('CLOSURE iteration')
                    LOG_DEBUG(f'A={A} B={B}')
                for rule in self.g.rule[B.name]:
                    rp = RulePtr(rule, 0)
                    if rp.name not in cc:
                        cc.append(rp)
                        changes += 1
            if changes == 0:
                break
        return cc

    def build_table (self):
        heading = [n for n in self.g.symbol.values()]
        self.tab = LRTable(heading)
        tab: LRTable = self.tab
        # tab.mode = 1
        if 0:
            import pprint
            pprint.pprint(self.link)
        for state in self.state.values():
            uuid = state.uuid
            link = self.link.get(uuid, None)
            LOG_VERBOSE(f'build table for I{state.uuid}')
            # LOG_VERBOSE(
            for rp in state.closure:
                rp: RulePtr = rp
                if rp.satisfied:
                    LOG_VERBOSE("  satisfied:", rp)
                    if rp.rule.head.name == 'S^':
                        if len(rp.rule.body) == 1:
                            action = Action(ActionName.ACCEPT, 0)
                            action.rule = rp.rule
                            tab.add(uuid, EOF.name, action)
                        else:
                            LOG_ERROR('error accept:', rp)
                    else:
                        action = Action(ActionName.REDUCE, rp.rule.index)
                        action.rule = rp.rule
                        # all terminals
                        for terminal_name in self.g.terminal.keys():
                            tab.add(uuid, terminal_name, action)
                        tab.add(uuid, EOF.name, action)
                elif rp.next.name in link:
                    target = link[rp.next.name]
                    action = Action(ActionName.SHIFT, target, rp.rule)
                    tab.add(uuid, rp.next.name, action)
                else:
                    LOG_ERROR('error link')
        return 0

#----------------------------------------------------------------------
# SLR Analyzer
#----------------------------------------------------------------------
class SLRAnalyzer (LR0Analyzer):

    def build_table (self):
        heading = [n for n in self.g.symbol.values()]
        self.tab = LRTable(heading)
        tab: LRTable = self.tab
        # tab.mode = 1
        if 0:
            import pprint
            pprint.pprint(self.link)
        for state in self.state.values():
            uuid = state.uuid
            link = self.link.get(uuid, None)
            LOG_VERBOSE(f'build table for I{state.uuid}')
            # LOG_VERBOSE(
            for rp in state.closure:
                rp: RulePtr = rp
                if rp.satisfied:
                    LOG_VERBOSE("  satisfied:", rp)
                    if rp.rule.head.name == 'S^':
                        if len(rp.rule.body) == 1:
                            action = Action(ActionName.ACCEPT, 0)
                            action.rule = rp.rule
                            tab.add(uuid, EOF.name, action)
                        else:
                            LOG_ERROR('error accept:', rp)
                    else:
                        action = Action(ActionName.REDUCE, rp.rule.index)
                        action.rule = rp.rule
                        # follow(head.name)
                        for symbol_name in self.ga.FOLLOW[rp.rule.head.name]:
                            tab.add(uuid, symbol_name, action)
                elif rp.next.name in link:
                    target = link[rp.next.name]
                    action = Action(ActionName.SHIFT, target, rp.rule)
                    tab.add(uuid, rp.next.name, action)
                else:
                    LOG_ERROR('error link')
        return 0

#----------------------------------------------------------------------
# conflict solver
#----------------------------------------------------------------------
class ConflictSolver (object):

    def __init__ (self, g:Grammar, tab: LRTable):
        self.g: Grammar = g
        self.tab: LRTable = tab
        self.conflicted = 0
        self.state = -1

    def error_rule (self, rule:Production, text:str):
        anchor = self.g.anchor_get(rule)
        if anchor is None:
            LOG_ERROR('error: %s'%text)
            return 0
        LOG_ERROR('error:%s:%d: %s'%(anchor[0], anchor[1], text))
        return 0

    def warning_rule (self, rule:Production, text:str):
        anchor = self.g.anchor_get(rule)    # (filename, line_num)
        if anchor is None:
            LOG_ERROR('warning: %s'%text)
            return 0
        LOG_ERROR('warning:%s:%d: %s'%(anchor[0], anchor[1], text))
        return 0

    def _conflict_type (self, action1:Action, action2:Action):
        if action1.name == ActionName.SHIFT:
            if action2.name == ActionName.SHIFT:
                return 'shift/shift'
            elif action2.name == ActionName.REDUCE:
                return 'shift/reduce'
        elif action1.name == ActionName.REDUCE:
            if action2.name == ActionName.SHIFT:
                return 'shift/reduce'
            elif action2.name == ActionName.REDUCE:
                return 'reduce/reduce'
        n1 = ActionName(action1.name)
        n2 = ActionName(action2.name)
        return '%s/%s'%(n1.name, n2.name)

    def process (self):
        tab: LRTable = self.tab
        self.state = -1
        for row in tab.rows:
            self.state += 1
            for key in list(row.keys()):
                cell = row[key]
                if not cell:
                    continue
                if len(cell) <= 1:
                    continue
                self._solve_conflict(cell)
        return 0

    def _solve_conflict (self, actionset):
        if not actionset:
            return 0
        if len(actionset) <= 1:
            return 0
        final = None
        for action in actionset:
            if final is None:
                final = action
                continue
            final = self._compare_rule(final, action)
        if isinstance(actionset, set):
            actionset.clear()
            actionset.add(final)
        elif isinstance(actionset, list):
            actionset.clear()
            actionset.push(final)
        return 0

    def warning_conflict (self, action1:Action, action2:Action):
        rule1:Production = action1.rule
        rule2:Production = action2.rule
        ctype:str = self._conflict_type(action1, action2)
        text = 'conflict %d %s with'%(self.state, ctype)
        text += ' ' + str(rule2)
        self.warning_rule(rule1, text)

    def _pick_shift (self, action1:Action, action2:Action, warning = False):
        if action1.name == ActionName.SHIFT:
            if warning:
                self.warning_rule(action2.rule, 'discard rule: %s'%str(action2.rule))
            return action1
        elif action2.name == ActionName.SHIFT:
            if warning:
                self.warning_rule(action2.rule, 'discard rule: %s'%str(action1.rule))
            return action2
        return action1

    def _pick_reduce (self, action1:Action, action2:Action, warning = False):
        if action1.name == ActionName.REDUCE:
            if warning:
                self.warning_rule(action2.rule, 'discard rule: %s'%str(action2.rule))
            return action1
        elif action2.name == ActionName.REDUCE:
            if warning:
                self.warning_rule(action2.rule, 'discard rule: %s'%str(action1.rule))
            return action2
        return action1

    def _compare_rule (self, action1:Action, action2:Action):
        rule1:Production = action1.rule
        rule2:Production = action2.rule
        if rule1.precedence is None:
            self.warning_conflict(action1, action2)
            if rule2.precedence is None:
                return self._pick_shift(action1, action2, True)
            return action2
        elif rule2.precedence is None:
            self.warning_conflict(action1, action2)
            return action1
        n1 = rule1.precedence
        n2 = rule2.precedence
        if n1 not in self.g.precedence:
            self.warning_rule(rule1, 'precedence %s not defined'%n1)
            return action1
        if n2 not in self.g.precedence:
            self.warning_rule(rule2, 'precedence %s not defined'%n2)
            return action1
        p1:int = self.g.precedence[n1]
        p2:int = self.g.precedence[n2]
        if p1 > p2:
            return action1
        elif p1 < p2:
            return action2
        a1:str = self.g.assoc[n1]
        a2:str = self.g.assoc[n2]
        if a1 == 'left':
            return self._pick_reduce(action1, action2)
        elif a1 == 'right':
            return self._pick_shift(action1, action2)
        return action1


#----------------------------------------------------------------------
# LexerError
#----------------------------------------------------------------------
class LexerError (Exception):
    def __init__ (self, error, line, column):
        super(LexerError, self).__init__(error)
        self.line = line
        self.column = column


#----------------------------------------------------------------------
# lexer
#----------------------------------------------------------------------
class Lexer (object):

    def __init__ (self):
        self.rules = []
        self.literal = {}
        self.actions = {}
        self.require = {}
        self.intercept_literal = True

    def clear (self):
        self.rules.clear()
        self.literal.clear()
        self.require.clear()
        return 0

    def push_skip (self, pattern:str):
        self.rules.append((None, pattern))
        return 0

    def _is_action (self, name:str) -> bool:
        return (name.startswith('{') and name.endswith('}'))

    def push_match (self, name:str, pattern:str):
        name = name.strip()
        if self._is_action(name):
            action = name[1:-1].strip('\r\n\t ')
            self.require[action] = len(self.rules)
            self.rules.append((self.__handle_action, pattern, action))
        else:
            self.rules.append((name, pattern))
        return 0

    def push_import_match (self, name:str, key:str):
        # print('import', name)
        key = key.strip()
        if name is None:
            name = key
        name = name.strip()
        if key not in PATTERN:
            raise LexerError('%s cannot be imported'%key, None, None)
        return self.push_match(name, PATTERN[key])

    def push_import_skip (self, key:str):
        if key not in PATTERN:
            raise LexerError('%s cannot be imported'%key, None, None)
        return self.push_skip(PATTERN[key])

    def push_literal (self, literal:str):
        self.literal[literal] = cstring.string_quote(literal)

    def __handle_action (self, text:str, action:str):
        if text in self.literal:
            if self.intercept_literal:
                return (self.literal[text], text)
        if action in self.actions:
            fn = self.actions[action]
            return fn(action, text)
        if '*' in self.actions:
            fn = self.actions['*']
            return fn(action, text)
        raise LexerError('missing action {%s}'%action, None, None)

    def __handle_literal (self, text:str):
        quoted = cstring.string_quote(text, True)
        return (quoted, text)

    def register (self, action:str, callback):
        self.actions[action] = callback
        return 0

    def __convert_to_literal (self, token):
        if cstring.string_is_quoted(token.name):
            return token
        name = token.value
        if not isinstance(name, str):
            return token
        if name not in self.literal:
            return token
        t = Token(self.literal[name], name, token.line, token.column)
        return t

    def tokenize (self, code) -> Generator[Token, None, None]:
        rules = [n for n in self.rules]
        for literal in self.literal:
            escape = re.escape(literal)
            rules.append((self.__handle_literal, escape))
        rules.append((self.__handle_mismatch, '.'))
        last_line = 1
        last_column = 1
        try:
            for token in tokenize(code, rules, '$'):
                last_line = token.line
                last_column = token.column
                if isinstance(token.value, str):
                    if not cstring.string_is_quoted(token.name):
                        if token.value in self.literal:
                            if self.intercept_literal:
                                token = self.__convert_to_literal(token)
                yield token
        except LexerError as e:
            e.line = last_line
            e.column = last_column
            raise e
        return 0

    def __handle_mismatch (self, text):
        return (cstring.string_quote(text), text)


#----------------------------------------------------------------------
# push down automata input
#----------------------------------------------------------------------
class PushDownInput (object):

    def __init__ (self, g:Grammar):
        self.g: Grammar = g
        self.lexer: Lexer = None
        self.it: collections.Iterator = None
        self.eof: bool = False
        self.matcher = None

    def open (self, code):
        if isinstance(code, str):
            self.lexer = self.__open_lexer()
            self.it = self.lexer.tokenize(code)
        elif hasattr(code, 'read'):
            content = code.read()
            self.lexer = self.__open_lexer()
            self.it = self.lexer.tokenize(content)
        elif hasattr(code, '__iter__'):
            self.it = iter(code)
        else:
            raise TypeError('invalid source type')
        self.eof = False
        return 0

    def read (self):
        if self.eof:
            return None
        try:
            token = next(self.it)
        except StopIteration:
            if not self.eof:
                self.eof = True
                return Token('$', '', None, None)
            return None
        if token.name == '$':
            self.eof = True
        return token

    def __open_lexer (self):
        lexer: Lexer = Lexer()
        for scanner in self.g.scanner:
            cmd: str = scanner[0].strip()
            if cmd in ('ignore', 'skip'):
                lexer.push_skip(scanner[1])
            elif cmd == 'match':
                lexer.push_match(scanner[1], scanner[2])
            elif cmd == 'import':
                lexer.push_import_match(scanner[1], scanner[2])
        for terminal in self.g.terminal.values():
            if cstring.string_is_quoted(terminal.name):
                text = cstring.string_unquote(terminal.name)
                lexer.push_literal(text)
        lexer.register('*', self.__handle_lexer_action)
        # lexer.push_literal('if')
        return lexer

    def __handle_lexer_action (self, action, text):
        if self.matcher is not None:
            clsname = self.matcher.__class__.__name__
            if hasattr(self.matcher, action):
                func = getattr(self.matcher, action)
                return func(text)
            else:
                raise TypeError('method "%s" is undefined in %s'%(action, clsname))
        return (cstring.string_quote('{%s}'%action), text)


#----------------------------------------------------------------------
# match action
#----------------------------------------------------------------------
class MatchAction (object):
    def __init__ (self):
        action = {}
        for name, func in self.__class__.__dict__.items():
            if not name.startswith('__'):
                action[name] = func
        self._MATCH_ACTION_ = action


#----------------------------------------------------------------------
# LR Push Down Automata 下推自动机
#----------------------------------------------------------------------
'''
@web: https://www.cnblogs.com/bryce1010/p/9387114.html
采用下推自动机这种数据模型。包括以下几个部分：
    1. 输入带：输入的 Token 流。
    2. 分析栈：包括状态栈和文法符号栈两部分。(state_0, None) 为分析开始前预先放在栈里的初始状态和句子括号。
    3. LR 分析表：包括动作表(ACTION)和状态转移表(GOTO)两张表。

PDA 算法：
置 ip 指向输入串 w 的第一个符号
    令 Si 为栈顶状态
    a 是 ip 指向的符号（当前输入符号）
    PUSH S0, None (进栈)
    BEGIN (重复开始)
        IF ACTION[Si,a]=Sj THEN
            BEGIN
                PUSH j,a (进栈)
                ip 前进 (指向下一输入符号)
            END
        ELSE IF ACTION[Si,a]=rj (若第 j 条产生式为 A→β) THEN
            BEGIN
                pop |β| 项（弹出 β 长度的项）
                若当前栈顶状态为 Sk:
                    push GOTO[Sk,A] , A (进栈)
            END
        ELSE IF ACTION[Si,a]=acc THEN
            return (成功）
        ELSE error
    END. (重复结束)
'''
class PDA (object):

    def __init__ (self, g:Grammar, tab:LRTable):
        self.g: Grammar = g
        self.tab: LRTable = tab
        self.input: PushDownInput = PushDownInput(self.g)
        self.state_stack = []
        self.symbol_stack = []
        self.value_stack = []   # token value
        self.input_stack = []
        self.current = None
        self._semantic_action = None
        self._lexer_action = None
        self._is_accepted = False
        self.accepted: bool = False
        self.error = None
        self.result = None
        self.debug = False
        self.filename = '<buffer>'
        self.analysis_table = [["Step", "State", "Symbol Stack", "Lookahead", "Input", "Action"]]
        self.current_action = ""

    def install_semantic_action (self, obj):
        self._semantic_action = obj
        return 0

    def install_lexer_action (self, obj):
        self._lexer_action = obj
        self.input.matcher = obj
        return 0

    def error_token (self, token:Token, *args):
        if not token.line:
            LOG_ERROR(*args)
        else:
            msg = 'error:%s:%d:'%(self.filename, token.line)
            LOG_ERROR(msg, *args)
        return 0

    def open (self, code):
        self.state_stack.clear()
        self.symbol_stack.clear()
        self.value_stack.clear()
        self.input_stack.clear()
        self.input.open(code)
        self.accepted: bool = False
        self.error = None
        self.state_stack.append(0)
        self.symbol_stack.append(EOF)
        self.value_stack.append(None)
        self.current: Token = self.input.read()
        self.result = None
        return 0

    def step (self):
        self.__append_analysis_table()
        if self.accepted:
            return -1
        elif self.error:
            return -2
        if len(self.state_stack) <= 0:
            LOG_ERROR('PDA fatal error')
            assert len(self.state_stack) > 0
            return -3
        state: int = self.state_stack[-1]
        tab: LRTable = self.tab
        if state not in tab:
            LOG_ERROR('state %d does not in table')
            assert state in tab
            return -4
        lookahead: Token = self.current
        data = tab.rows[state].get(lookahead.name, None)
        if not data:
            self.error = 'unexpected token: %r'%lookahead
            self.error_token(lookahead, self.error)
            return -5
        assert len(data) == 1   # if len(data) > 1, maybe happen to conflict (shift and reduce conflict)
        action: Action = list(data)[0]
        if not action:
            self.error = 'invalid action'
            self.error_token(lookahead, 'invalid action:', str(action))
            return -6
        retval = 0
        # if shift, push state_stack
        # if reduce, pop state_stack
        if action.name == ActionName.SHIFT:
            symbol: Symbol = Symbol(lookahead.name, True)
            newstate: int = action.target
            self.state_stack.append(newstate)
            self.symbol_stack.append(symbol)
            self.value_stack.append(lookahead.value)
            self.input_stack.append(lookahead.value)
            self.current = self.input.read()
            self.current_action = 'shift/%d'%action.target
            if self.debug:
                print('action: shift/%d'%action.target)
            retval = 1
        # shift after reduce
        elif action.name == ActionName.REDUCE:
            retval = self.__proceed_reduce(action.target)
        elif action.name == ActionName.ACCEPT:
            assert len(self.state_stack) == 2
            self.accepted = True
            self.result = self.value_stack[-1]
            self.current_action = 'accept'
            if self.debug:
                print('action: accept')
        elif action.name == ActionName.ERROR:
            self.error = 'syntax error'
            self.current_action = 'error'
            if hasattr(action, 'text'):
                self.error += ': ' + getattr(action, 'text')
            self.error_token(lookahead, self.error)
            if self.debug:
                print('action: error')
            retval = -7
        if self.debug:
            print()
        self.__append_analysis_table(-1)
        return retval

    # stack: 0 1 2 3 4(top)
    def __generate_args (self, size):
        if len(self.state_stack) <= size:
            return None
        top = len(self.state_stack) - 1
        args = []
        for i in range(size + 1):
            args.append(self.value_stack[top - size + i])
        return args

    def __execute_action (self, rule: Production, actname: str, actsize: int):
        value = None
        args = self.__generate_args(actsize)
        if not self._semantic_action:
            return 0, None
        name = actname
        if name.startswith('{') and name.endswith('}'):
            name = name[1:-1].strip()
        callback = self._semantic_action    # class
        if not hasattr(callback, name):
            raise KeyError('action %s is not defined'%actname)
        func = getattr(callback, name)
        value = func(rule, args)
        return 1, value

    def __rule_eval (self, rule: Production):
        parent: Production = rule
        if hasattr(rule, 'parent'):
            parent: Production = rule.parent
        size = len(rule.body)
        if len(self.state_stack) <= size:
            self.error = 'stack size is not enough'
            raise ValueError('stack size is not enough')
        value = None
        executed = 0
        action_dict = rule.action and rule.action or {}
        for pos, actions in action_dict.items():
            if pos != size:
                LOG_ERROR('invalid action pos: %d'%pos)
                continue
            for action in actions:
                if isinstance(action, str):
                    actname = action
                    actsize = size
                elif isinstance(action, tuple):
                    actname = action[0]
                    actsize = action[1]
                else:
                    LOG_ERROR('invalid action type')
                    continue
                hr, vv = self.__execute_action(parent, actname, actsize)
                if hr > 0:
                    value = vv
                    executed += 1
        # if not action, use default action
        if executed == 0:
            args = self.__generate_args(size)
            value = Node(rule.head, args[1:])
        return value

    def __proceed_reduce (self, target: int):
        rule: Production = self.g.production[target]
        size = len(rule.body)
        value = self.__rule_eval(rule)
        # pop by length(body of production)
        for i in range(size):
            self.state_stack.pop()
            self.symbol_stack.pop()
            self.value_stack.pop()
        assert len(self.state_stack) > 0
        top = len(self.state_stack) - 1  # noqa
        state = self.state_stack[-1]
        tab: LRTable = self.tab
        if state not in tab:
            LOG_ERROR('state %d does not in table')
            assert state in tab
            return -10
        data = tab.rows[state].get(rule.head.name, None)
        if not data:
            self.error = 'reduction state mismatch'
            self.error_token(self.current, self.error)
            return -11
        action: Action = list(data)[0]
        if not action:
            self.error = 'invalid action: %s'%str(action)
            self.error_token(self.current, self.error)
            return -12
        if action.name != ActionName.SHIFT:
            self.error = 'invalid action name: %s'%str(action)
            self.error_token(self.current, self.error)
            return -13
        newstate = action.target
        self.state_stack.append(newstate)
        self.symbol_stack.append(rule.head)
        self.value_stack.append(value)
        self.current_action = 'reduce/%d -> %s'%(target, rule)
        if self.debug:
            print('action: reduce/%d -> %s'%(target, rule))
        return 0

    def is_stopped (self) -> bool:
        if self.accepted:
            return True
        if self.error:
            return True
        return False

    def run (self):
        while not self.is_stopped():
            if self.debug:
                self.print()
            self.step()
        if self.debug:
            self.print_analysis_table()
        return self.result

    def print (self):
        print('stack:', self.state_stack)
        text = '['
        symbols = []
        for n in self.symbol_stack:
            symbols.append(str(n))
        text += (', '.join(symbols)) + ']'
        print('symbol:', text)
        print('lookahead:', self.current and self.current.name or None)
        return 0

    def __append_analysis_table (self, pos=0):
        if pos == 0:
            self.row = []
            self.analysis_table.append(self.row)
            self.row.append(len(self.analysis_table)-1)
            self.row.append(", ".join([str(n) for n in self.state_stack]))
            self.row.append(", ".join([str(n) for n in self.symbol_stack]))
            self.row.append(self.current.name)
            return
        self.row.append("".join([str(n) for n in self.input_stack]))
        self.row.append(self.current_action)
        self.row = None

    def print_analysis_table (self):
        text = cstring.tabulify(self.analysis_table, 1)
        print(text)


#----------------------------------------------------------------------
# create parser
#----------------------------------------------------------------------
class Parser (object):

    def __init__ (self, g:Grammar, tab:LRTable):
        self.g:Grammar = g
        self.tab:LRTable = tab
        self.pda:PDA = PDA(g, tab)
        self.error = None

    def __call__ (self, code, debug = False):
        self.error = None
        self.pda.open(code)
        self.pda.debug = debug
        self.pda.run()
        if self.pda.accepted:
            return self.pda.result
        self.error = self.pda.error
        return None


#----------------------------------------------------------------------
# create parser with grammar
#----------------------------------------------------------------------
def __create_with_grammar(g:Grammar, semantic_action, 
                          lexer_action, algorithm):
    if g is None:
        return None
    if algorithm.lower() in ('lr1', 'lr(1)'):
        algorithm = 'lr1'
    elif algorithm.lower() in ('lalr', 'lalr1', 'lalr(1)'):
        algorithm = 'lalr'
    elif algorithm.lower() in ('lr0', 'lr(0)'):
        algorithm = 'lr0'
    elif algorithm.lower() in ('slr', 'slr1', 'slr(1)'):
        algorithm = 'slr'
    else:
        algorithm = 'lr1'
    if algorithm == 'lr1':
        analyzer = LR1Analyzer(g)
    elif algorithm == 'lr0':
        analyzer = LR0Analyzer(g)
    elif algorithm == 'slr':
        analyzer = SLRAnalyzer(g)
    else:
        analyzer = LALRAnalyzer(g)
    hr = analyzer.process()
    if hr != 0:
        return None
    tab:LRTable = analyzer.tab
    cs:ConflictSolver = ConflictSolver(g, tab)
    cs.process()
    parser = Parser(g, tab)
    if semantic_action:
        parser.pda.install_semantic_action(semantic_action)
    if lexer_action:
        parser.pda.install_lexer_action(lexer_action)
    return parser


#----------------------------------------------------------------------
# create_parser
#----------------------------------------------------------------------
def create_parser(grammar_bnf: str, 
                  semantic_action = None,
                  lexer_action = None,
                  algorithm = 'lr1'):
    g = load_from_string(grammar_bnf)
    return __create_with_grammar(g, semantic_action, lexer_action, algorithm)


#----------------------------------------------------------------------
# create from file
#----------------------------------------------------------------------
def create_parser_from_file(grammar_file_name: str,
                            semantic_action = None,
                            lexer_action = None,
                            algorithm = 'lr1'):
    g = load_from_file(grammar_file_name)
    return __create_with_grammar(g, semantic_action, lexer_action, algorithm)


#----------------------------------------------------------------------
# testing suit
#----------------------------------------------------------------------
if __name__ == '__main__':
    def test1():
        g = load_from_file('grammar/test_bnf.txt')
        g.print()
        return 0
    def test2():
        g = load_from_file('grammar/test_bnf.txt')
        la = LR1Analyzer(g)
        la.process()
        import pprint
        pprint.pprint(la.link)
        # g.print()
        print(len(la.state))
        tab: LRTable = la.tab
        tab.print()
        return 0
    def test3():
        g = load_from_file('grammar/test_bnf.txt')
        la = LALRAnalyzer(g)
        la.process()
        for cc in la.state.values():
            cc.print()
        pprint.pprint(la.link)
        print()
        pprint.pprint(la.route)
        la.tab.print()
        return 0
    def test4():
        grammar_definition = r'''
        E: E '+' T | E '-' T | T;
        T: T '*' F | T '/' F | F;
        F: number | '(' E ')';
        %token number
        @ignore [ \t\n\n]*
        @match number \d+
        '''
        parser = create_parser(grammar_definition,
                               algorithm = 'lr1')
        print(parser('1+2*3'))
        return 0
    def test5():
        g = load_from_file('grammar/func.ebnf')
        g.print()
        print()

        ga = GrammarAnalyzer(g)
        ga.process()
        ga.print_epsilon()
        ga.print_first()
        print(ga.is_LL1())

        la = LR1Analyzer(g)
        la.process()
        import pprint
        pprint.pprint(la.link)
        # g.print()
        print()

        for uuid, state in la.state.items():
            state.print()
        print(len(la.state))
        tab: LRTable = la.tab
        tab.print()
        print()

        class Func:
            def get_id(self, rule, args):
                return args[1]
            def get_func(self, rule, args):
                return [args[1], args[3]]
            def get_null(self, rule, args):
                return None
            def get(self, rule, args):
                return args[1]
            def get_list(self, rule, args):
                return [args[1]] + [args[3]]
        parser = create_parser_from_file("grammar/func.ebnf",
                                        Func(),
                                        algorithm = 'lalr')
        print(parser("max(min(1, 2), max(1, 2))"))
        return 0
    def test6():
        grammar_definition = r'''
        E:  T E' ;
        E': '+' T E' | ;
        T:  F T' ;
        T': '*' F T' | ;
        F:  '(' E ')' | number ;
        % token number
        @ignore [ \t\n\n]*
        @match number \d+
        '''

        grammar_definition = r'''
        T:  A F B number | A F B "(" | A F F |;
        F:  number ;
        A:  number ;
        B:  number ;
        % token number
        @ignore [ \t\n\n]*
        @match number \d+
        '''

        grammar_definition = r'''
        Q:  R 'b' | 'b' ;
        R:  S 'a' | 'a' ;
        S:  Q 'c' | 'c' ;
        '''

        # g = load_from_file('grammar/func.ebnf')
        g = load_from_string(grammar_definition)
        g.print()
        print()

        la = LL1Analyzer(g)
        la.process()

    def test7():
        grammar_definition = r'''
        E: E '+' T | T;
        T: T '*' F | F;
        F: number | '(' E ')';
        %token number
        @ignore [ \t\n\n]*
        @match number \d+
        '''

        g = load_from_string(grammar_definition)
        g.print()
        print()

        slr = SLRAnalyzer(g)
        slr.process()
        slr.tab.print()

    def test8():
        grammar_definition = r'''
        S: L '=' R | R;
        L: '*' R | number;
        R: L;
        %token number
        @ignore [ \t\n\n]*
        @match number \d+
        '''

        g = load_from_string(grammar_definition)
        g.print()
        print()

        slr = SLRAnalyzer(g)
        slr.process()
        slr.tab.print()

    def test9():
        grammar_definition = r'''
        E: E '+' T | T;
        T: T '*' F | F;
        F: number | '(' E ')';
        %token number
        @ignore [ \t\n\n]*
        @match number \d+
        '''

        g = load_from_string(grammar_definition)
        g.print()
        print()

        lr = LR0Analyzer(g)
        lr.process()
        lr.tab.print()

    def test10():
        grammar_definition = r'''
        E: E '+' T | T;
        T: T '*' F | F;
        F: number | '(' E ')';
        %token number
        @ignore [ \t\n\n]*
        @match number \d+
        '''
        parser = create_parser(grammar_definition,
                               algorithm = 'lalr')
        print(parser('1*(2+3)', debug=True))

    def test11():
        grammar_definition = r'''
        S: L '.' L | L ;
        L: L B | B ;
        B: '0' | '1' ;
        '''
        parser = create_parser(grammar_definition,
                               algorithm = 'lr1')
        print(parser('011.101', debug=True))

    test11()