from collections import namedtuple
import inspect
import re

def unwrap_with_context_if_needed(val, context, *args, **kwargs):
  # unwraps with context only user defined functions and lambdas
  if type(val).__name__ == 'function':
    sig = inspect.signature(val)
    if 'context' in sig.parameters:
      b = sig.bind_partial(*args, **kwargs)
      b.apply_defaults()
      b.arguments['context'] = context
      return val(*b.args, **b.kwargs)
    return val(*args, **kwargs)
  if callable(val):
    return val(*args, **kwargs)
  return val

class FormatStr:
  @staticmethod
  def Shorten(s, w, ratio=0.5):
    if len(s) > w:
      left = int(w*ratio) - 2
      if left < 0:
        left = 0
      right = w - left - 4
      sl = " ..."
      if left > 0:
        sl = s[:left]
      sr = "... "
      if right > 0:
        sr = s[-right:]
      if left > 0 and right > 0:
        s = sl + " .. " + sr
      else:
        s = sl + sr
    return s

  @staticmethod
  def Part(s, pos, width, zero_pos=-1):
    # zero_pos = -1 - means to do not show position symbol
    start = pos - zero_pos if zero_pos >= 0 else pos
    start = start if start >= 0 else 0
    end   = start + width

    past = s[start:pos]
    future = s[pos:end]

    past_r = repr(past)[1:-1]
    future_r = repr(future)[1:-1]

    past_delta = len(past_r) - len(past)
    future_delta = len(future_r) - len(future)

    pd = 0
    fd = 0

    if len(past_r) + len(future_r) > width:
      delta = len(past_r) + len(future_r) - width
      pd = (delta * past_delta) // (past_delta + future_delta + 1)
      fd = delta - pd

    if start > 0 or pd > 0:
      past_r = "..." + past_r[pd + 3:]
    if end < len(s) or fd > 0:
      future_r = future_r[:-fd-3] + "..."
    ns = f"{past_r}{'🢂◈' if zero_pos >=0 else ''}{future_r}"
    return ns

class Token(namedtuple('Token', ['stream', 'parser', 'start', 'end'])):
  __slots__=()
  def set_parser(self, parser):
    return Token(self.stream, parser, self.start, self.end)
  def set_end(self, end):
    return Token(self.stream, self.parser, self.start, end)
  def set_start(self, start):
    return Token(self.stream, self.parser, start, self.end)
  @property
  def data(self):
    return self.stream.data[self.start:self.end]
  @property
  def text(self):
    return repr(self.data)[1:-1]
  def __repr__(self):
    line = FormatStr.Part(self.stream.data, self.start, 20)
    parser_name = FormatStr.Shorten(repr(self.parser), 30)
    return f"Token('{line}', {parser_name}, {self.start}, {self.end})"
  @staticmethod
  def default(stream, parser):
    return Token(stream, parser, stream.pos, stream.pos)

class Result:
  def __init__(self, *args, **kw):
    self._token = None
    self._value = None
    self._err_msg = None
    if len(args) != 0 or len(kw) != 0:
      self._token = Token(*args, **kw)
    if self._token:
      self._value = self._token.data

  def __bool__(self):
    return self._token is not None

  def invalidate(self, err_msg = None):
    self._token = None
    self._value = None
    self._err_msg = err_msg

  @property
  def token(self):
    return self._token

  @property
  def err_msg(self):
    return self._err_msg

  @property
  def parser(self):
    if self._token:
      return self._token.parser
    return None

  @parser.setter
  def parser(self, parser):
    if self._token:
      self._token = self._token.set_parser(parser)

  @property
  def value(self):
    return self._value

  @value.setter
  def value(self, val):
    self._value = val

  def __repr__(self):
    if self:
      val = repr(self._value)
      parser = repr(self._token.parser)[1:-1]
      text = f"{val}\n" + \
            (f"('{parser}'@'{self._token})" if self._token else "")
    else:
      text = f"<INVALID>\n{self.err_msg or ''}"
    return text

class ResultProcessor(list):
  def __init__(self, elt = None):
    if elt is not None:
      self.extend(elt)

  def __mod__(self, p):
    name = repr(p)
    if type(p) is tuple:
      p, name = p
    return ResultProcessor(self[0:] + [(0, p, name)])

  def __floordiv__(self, c):
    name = repr(c)
    if type(c) is tuple:
      c, name = c
    return ResultProcessor(self[0:] + [(1, c, name)])

  def __call__(self, v):
    for t, p, n in self:
      if not v:
        break
      assert t in (0,1)
      if t == 0:
        try:
          v.value = unwrap_with_context_if_needed(p, v.token.stream.context, v.value)
        except Exception as err:
          text =  f"Processing '{repr(n)[1:-1]}' failed on value {repr(v.value)}\n"
          text += f"Exception {err=}, {type(err)=}\n"
          text += f"Token: ... {v.token.text} ...\n"
          text += f"Stream:\n"
          text += repr(v.token.stream)
          v.invalidate(text)
      elif t == 1:
        ok = unwrap_with_context_if_needed(p, v.token.stream.context, v.value)
        if not ok:
          text = f"Check '{repr(n)[1:-1]}' failed on value {repr(v.value)}\n"
          text += f"Token: ... {v.token.text} ...\n"
          text += f"Stream:\n"
          text += repr(v.token.stream)
          v.invalidate(text)
    return v

class Context():
  def __init__(self, ctx = None):
    self._top = ctx or dict()
    self._stack = []

  def clear(self):
    self._stack = []

  def push(self):
    self._stack.append(dict())

  def pop(self):
    self._stack.pop()

  @property
  def top(self):
    return self._top

  class lookup:
    def __init__(self, ctx):
      self.__ctx = ctx

    not_found = object()

    def get(self, idx, default=None):
      if len(self.__ctx._stack) > 0:
        for i in range(len(self.__ctx._stack)-2, -1, -1):
          if idx in self.__ctx._stack[i]:
            return self.__ctx._stack[i][idx]
      return self.__ctx._top.get(idx, default)

    def __getitem__(self, idx):
      val = self.get(idx, Context.lookup.not_found)
      if val == Context.lookup.not_found:
        raise KeyError(idx)
      return val

  @property
  def upper(self):
    return Context.lookup(self)

  @property
  def local(self):
    return self._stack[-1] if len(self._stack) > 0 else None

  def __getitem__(self, key):
    if self.local and key in self.local:
      return self.local[key]
    return self.upper[key]

  def get(self, key, default=None):
    if self.local and key in self.local:
      return self.local[key]
    return self.upper.get(key, default)

  def __setitem__(self, key, val):
    self.local[key] = val

  def __delitem__(self, key):
    del self.local[key]

  #def __repr__(self):
    # TODO
    #pass

class Breakpoint():
  pass
  # __init__(self, stream)
  # add(self, parser, count=None, pos=None)
  # remove(self, bp_no)
  # __repr__
  # check(self, parser)
  #  breakpoint reached:
  #    parser info
  #    stream backtrace
  #    current context 
  #    etc

class Stream():
  def __init__(self, data, context = None, debug = False):
    self._data = data
    self._debug = debug
    self._context = Context(context)
    self.rewind()

  @property
  def data(self):
    return self._data

  @property
  def pos(self):
    return self._pos

  @pos.setter
  def pos(self, val):
    self._pos = val

  @property
  def context(self):
    return self._context

  def rewind(self):
    self._pos = 0
    self._log = []
    self._stack = []
    self._stack_idx = 0
    self._context.clear()

  def push(self, parser):
    self._context.push()
    if self._debug:
      self._log.append((self._stack_idx,self.pos, parser, 'v',))
      if self._stack_idx >= len(self._stack):
        self._stack.append((self.pos, parser,))
      else:
        self._stack[self._stack_idx] = (self.pos, parser,)
      self._stack_idx += 1

  def pop(self):
    self._context.pop()
    if self._debug:
      self._stack_idx -= 1
      assert self._stack_idx >= 0, "Error stream push()/pop() mismatch!"
      self.pos, parser = self._stack[self._stack_idx]
      self._log.append((self._stack_idx,self.pos, parser, '^',))

  def advance(self):
    self._context.pop()
    if self._debug:
      # just cut stack, position is kept
      _pos, parser = self._stack[self._stack_idx-1]
      self._log.append((self._stack_idx, self.pos, parser, '>',))
      self._stack = self._stack[0:self._stack_idx]
      self._stack_idx -= 1

  def __repr__log(self):
    if not self._debug:
      return "Stream debug is disabled."
    total_width = 120
    depth_width = 5
    ncall_width = 5
    name_width = max([len("parser")] + [len(pars.name) for d,pos,pars,s in self._log]) + 1
    loc_width = max([len("defined at")] + [len(pars.loc) for d,pos,pars,s in self._log]) + 1
    if name_width > 30:
      name_width = 30
    if loc_width > 20:
      loc_width = 20

    log_input_width = total_width - depth_width - ncall_width - name_width - loc_width - 9

    def log_line(depth, pos, name, loc, ncall, action):
      l = FormatStr.Part(self.data, pos, log_input_width-3, 5)
      name = FormatStr.Shorten(repr(name)[1:-1], name_width)
      loc = FormatStr.Shorten(loc, loc_width, 0)
      return f"{depth:<{depth_width}} │ {ncall:<{ncall_width}} │{action}│ {name:<{name_width}} │ {loc:<{loc_width}} │ {l}"

    s = FormatStr.Part(self.data, self.pos, total_width-9, 10)
    text  = f"Parsing log\n"
    text += f"{'━'*depth_width}━┯━{'━'*ncall_width}━┯━┯━{'━'*name_width}━┯━{'━'*loc_width}━┯{'━'*log_input_width}\n"
    text += f"{'depth':<{depth_width}} │ {'calls':<{ncall_width}} │A│ {'parser':<{name_width}} │ {'defined at':<{loc_width}} │ parser input\n"
    text += f"{'═'*depth_width}═╪═{'═'*ncall_width}═╪═╪═{'═'*name_width}═╪═{'═'*loc_width}═╪{'═'*log_input_width}"
    calls = dict()
    for depth, pos, par, action in self._log:
      ncall = calls.get(par, 0)
      if action == 'v':
        ncall += 1
      calls[par] = ncall
      text += "\n" + log_line(depth, pos, par.name, par.loc, ncall, action)
    text +=  f"\n{'━'*depth_width}━┷━{'━'*ncall_width}━┷━┷━{'━'*name_width}━┷━{'━'*loc_width}━┷{'━'*log_input_width}\n"
    return text

  def __repr__bt(self):
    # TODO: add info from context
    if not self._debug:
      return "Stream debug is disabled.\n"
    # TODO configurable columns widths
    total_width = 120
    name_width = max([len("parser")] + [len(pars.name) for pos,pars in self._stack]) + 1
    loc_width = max([len("defined at")] + [len(pars.loc) for pos,pars in self._stack]) + 1
    if name_width > 30:
      name_width = 30
    if loc_width > 20:
      loc_width = 20

    bt_input_width = total_width - name_width - loc_width - 4

    def bt_line(pos, name, loc):
      l = FormatStr.Part(self.data, pos, bt_input_width-3, 5)
      name = FormatStr.Shorten(repr(name)[1:-1], name_width)
      loc = FormatStr.Shorten(loc, loc_width, 0)
      return f"{name:<{name_width}} │ {loc:<{loc_width}} │ {l}"

    s = FormatStr.Part(self.data, self.pos, total_width-9, 10)
    text =  f"Parsing backtrase\n{'━'*total_width}\n"
    text += f"input ⮞ {s}\n{'━'*name_width}━┯━{'━'*loc_width}━┯{'━'*bt_input_width}\n"
    text += f"{'parser':<{name_width}} │ {'defined at':<{loc_width}} │ parser input\n"
    text += f"{'═'*name_width}═╪═{'═'*loc_width}═╪{'═'*bt_input_width}"
    for pos, par in self._stack:
      text += "\n" + bt_line(pos,par.name, par.loc)
    text +=  f"\n{'━'*name_width}━┷━{'━'*loc_width}━┷{'━'*bt_input_width}\n"
    return text

  @property
  def bt(self):
    return self.__repr__bt()

  @property
  def log(self):
    return self.__repr__log()

  def __repr__(self):
    bt = self.__repr__bt()
    log = self.__repr__log()
    return f"{bt}\n{log}\n"

class Parser:
  @staticmethod
  def _possible_unwrap(fn):
    if '__name__' in dir(fn) and fn.__name__ == '<lambda>' and fn.__code__.co_argcount == 0:
      return fn()
    return fn

  @staticmethod
  def _to_parser(p, loc, name = None):
    if isinstance(p, Parser):
      return p
    p = Parser(p, name, loc)
    return p

  @staticmethod
  def class_parser(cls):
    try:
      # check for private class fields
      for field_name in ["_" + cls.__name__+ "__parser", "__parser"]:
        p = getattr(cls,field_name, None)
        if p:
          loc = Parser._get_loc(3)
          p = Parser._to_parser(p, loc)
          setattr(cls, field_name, p)
          return p
      return None
    except:
      return None

  @staticmethod
  def _get_loc(frame=2):
    fr, filename, line, fname, lines, pos = \
      inspect.getouterframes(inspect.currentframe())[frame]
    return f"{filename}:{line}"

  def __init__(self, parser, name = None, loc = None):
    self.loc = loc if loc else Parser._get_loc()
    if isinstance(parser, Parser):
      name = parser._name
      parser = parser._parser
    if isinstance(parser, list):
      parser = [Parser._to_parser(p, self.loc) for p in parser]
    elif isinstance(parser, dict):
      parser = {k: Parser._to_parser(v, self.loc) for k,v in parser.items()}
    elif type(parser) is tuple:
      parser = tuple(Parser._to_parser(p, self.loc) for p in parser)
    elif type(parser) is not tuple and isinstance(parser, tuple) and '_fields' in dir(parser):
      parser = type(parser)(*[Parser._to_parser(p, self.loc) for p in parser])
    elif type(parser) is str:
      name = name or f"term('{parser}')"
    elif isinstance(parser, re.Pattern):
      # TODO: add selection of matching products
      # it will help to move some parsing logic to regexps and will gain some speed
      name = name or f"regexp{str(parser).removeprefix('re.compile')}"
    self._parser = parser
    if name is None:
      name = f"{repr(parser)}"
      if callable(parser) and '__name__' in dir(parser) and\
         '__code__' in dir(parser):
        cfname = parser.__code__.co_filename
        cline = parser.__code__.co_firstlineno
        cname = parser.__name__
        name = f"{cname}@{cfname}:{cline}"
    self._name = name
    self._processor = ResultProcessor()

  @property
  def loc(self):
    return self._loc

  @loc.setter
  def loc(self, l):
    self._loc = l

  @property
  def name(self):
    return self._name

  @name.setter
  def name(self, n):
    self._name = n
    p = self._parser
    if type(p) is not tuple and isinstance(p, tuple) and '_fields' in dir(p):
      t = namedtuple(n, p._parser._fields)
      p = t(*p._parser)
    self._parser = p

  def __repr__(self):
    return f"{repr(self.name)[1:-1]}@{self.loc}"

  def __call__str(self, s):
    if s.data.startswith(self._parser, s.pos):
      start = s.pos
      end = start + len(self._parser)
      s.pos = end
      return Result(s, self.name, start, end)
    return Result()

  def __call__re_pattern(self, s):
    m = self._parser.match(s.data, s.pos)
    if m:
      s.pos = m.end()
      return Result(s, self.name, m.start(), m.end())
    return Result()

  def __call__dict(self, s):
    # parsing allow multiple items per key, i.e. it is actually bags
    result = Result()
    result.value = {k:[] for k in self._parser}
    match = True
    while match:
      match = False
      for k, p in self._parser.items():
        r = p(s)
        if r:
          match = True
          if result:
            result._token = result._token.set_end(r.token.end)
          else:
            result._token = r._token
          if r.value is not None:
            result.value[k].append(r.value)
          break
    return result

  def __call__namedtuple(self, s):
    result = Result()
    for p in self._parser:
      r = p(s)
      if not r:
        return r
      if not result:
        result = r
        result.value = [r.value]
      else:
        result.value.append(r.value)
        result._token = result._token.set_end(r.token.end)
    if result:
      result.value = type(self._parser)(*result.value)
    return result

  def __call__tuple(self, s):
    for p in self._parser:
      r = p(s)
      if r:
        return r
    return Result()

  def __call__list(self, s):
    result = Result()
    for p in self._parser:
      r = p(s)
      if not r:
        return r
      if not result:
        result = r
        if result.value is not None:
          result.value = [result.value]
        else:
          result.value = []
      else:
        if r.value is not None:
          result.value.append(r.value)
        result._token = result._token.set_end(r.token.end)
    return result

  def __call__(self, s=None):
    if s is None:
      # special case to close parser, i.e. to not be extended by &, | or + operatios
      loc = Parser._get_loc()
      name = f"∎{self.name}"
      parser = Parser(lambda s: self(s), name, loc)
      return parser
    parsing_from_string = False
    parser_is_class = False
    if type(s) is str:
      # call with string, enstead of stream is for
      # debug purposes only
      s = Stream(s, debug = True)
      parsing_from_string = True
    s.push(self)
    # TODO:
    # Design choice:
    # 1. unwrap once on first execution
    # 2. or unwrap on every execution?
    # pros/cons:
    # 1 faster but captures and freezes context
    # 2 slower, but more complex schemas are possible
    # for now variant No 1 is implemented
    self._parser = Parser._possible_unwrap(self._parser)
    if type(self._parser) is list:
      r = self.__call__list(s)
    elif type(self._parser) is dict:
      r = self.__call__dict(s)
    elif type(self._parser) is tuple:
      r = self.__call__tuple(s)
    elif isinstance(self._parser, tuple) and '_fields' in dir(self._parser):
      r = self.__call__namedtuple(s)
    elif type(self._parser) is str:
      r = self.__call__str(s)
    elif isinstance(self._parser, re.Pattern):
      r = self.__call__re_pattern(s)
    else:
      p = Parser.class_parser(self._parser)
      if p:
        parser_is_class = True
        r = p(s)
      else:
        r = self._parser(s)
    r.parser = self
    r = self._processor(r)
    if r:
      s.advance()
      if parser_is_class:
        # if self._parser.parser is Parser, then special construction of obj is used:
        #   r.value is list = *args
        #   r.value is dict = **kwargs
        #   r.value is (list, dict) = *args, **kwargs
        #   otherwise just call
        #   ^^^ rationale: to simplify AST construction via namedtuples
        # else if user defined parser is used, then just call constructor with r.value
        p = Parser.class_parser(self._parser)
        if type(p) is Parser:
          if isinstance(r.value, list):
            r.value = self._parser(r.value)
          elif isinstance(r.value, tuple):
            r.value = self._parser(*r.value)
          elif type(r.value) is dict:
            r.value = self._parser(**r.value)
          else:
            r.value = self._parser(r.value)
        else:
          r.value = self._parser(r.value)
    else:
      s.pop()
    if not r and parsing_from_string:
      r._err_msg = repr(s)
    return r

  def __or__(self, other):
    loc = Parser._get_loc()
    other = Parser._to_parser(other, loc)
    p = self._parser
    # if attached some checks or processors, parser become closed, i.e. cannot be extended
    if not type(p) is tuple or self._processor:
      p = (self, )
    p = p + (other, )
    name = "(" + "|".join(i.name for i in p) + ")"
    p = Parser(p, name, loc)
    return p

  def __ror__(self, other):
    loc = Parser._get_loc()
    other = Parser._to_parser(other, loc)
    p = self._parser
    if not type(p) is tuple or self._processor:
      p = (self, )
    p = (other, ) + p
    name = "(" + "|".join(i.name for i in p) + ")"
    p = Parser(p, name, loc)
    return p

  def __and__(self, other):
    loc = Parser._get_loc()
    other = Parser._to_parser(other, loc)
    p = self._parser
    # if attached some checks or processors, parser become closed, i.e. cannot be extended
    # and treated as single parser
    if not type(p) is list or self._processor:
      p = [self]
    else:
      p = p.copy()
    p.append(other)
    name = "(" + "&".join(i.name for i in p) + ")"
    p = Parser(p, name, loc)
    return p

  def __rand__(self, other):
    loc = Parser._get_loc()
    other = Parser._to_parser(other,loc)
    p = self._parser
    if not type(p) is list or self._processor:
      p = [self]
    else:
      p = p.copy()
    p.insert(0, other)
    name = "(" + "&".join(i.name for i in p) + ")"
    p = Parser(p, name, loc)
    return p

  @staticmethod
  def __add__internal(l, r, name, loc):
    if type(l) is dict and type(r) is dict:
      p = {**l, **r}
    elif type(l) is tuple and '_fields' in l.__dict__ \
         and type(r) is tuple and '_fields' in r.__dict__:
      t = namedtuple(name, l._fields + r._fields)
      p = t(*l, *r)
    else:
      raise ValueException("Wrong value for __add__")
    p = Parser(p, name, loc)
    return p

  def __add__(self, other):
    loc = Parser._get_loc()
    other = Parser._to_parser(other,loc)
    name = f"({self.name})+({other.name})"
    if self._processor or other._processor:
      raise ValueError("Cannot merge parsers with attached value processing/checking")
    return Parser.__add__internal(self._parser, other._parser, name, loc)

  def __radd__(self, other):
    loc = Parser._get_loc()
    other = Parser._to_parser(other,loc)
    name = f"({other.name})+({self.name})"
    if self._processor or other._processor:
      raise ValueError("Cannot merge parsers with attached value processing/checking")
    return Parser.__add__internal(other._parser, self._parser, name, loc)

  def __neg__(self):
    loc = Parser._get_loc()
    name = f"(-({self._name}))"
    def m(s):
      r = self(s)
      r.value = None
      return r
    return Parser(m, name, loc)

  def __invert__(self):
    loc = Parser._get_loc()
    name = f"~({self._name})"
    def m(s):
      r = self(s)
      if not r:
        r = Result(s, '', s.pos, s.pos)
        r.value = None
      return r
    return Parser(m, name, loc)

  def __truediv__(self, val):
    loc = Parser._get_loc()
    name = f"(({self._name})/{val})"
    def m(s):
      r = self(s)
      if not r:
        r = Result(s, '', s.pos, s.pos)
        r.value = unwrap_with_context_if_needed(val, s.context)
      return r
    return Parser(m, name, loc)

  def __eq__(self, other):
    return id(self) == id(other)

  def __hash__(self):
    return id(self)

  def __ge__(self, val):
    loc = Parser._get_loc()
    name = f"(({self._name})>>={val})"
    def m(s):
      r = self(s)
      if r:
        r.value = unwrap_with_context_if_needed(val, s.context)
      return r
    return Parser(m, name, loc)

  @staticmethod
  def __rshift__internal(left, right, loc):
    def m(s):
      r = left(s)
      if r:
        next_r = right(s)
        if next_r:
          next_r._token = next_r._token.set_start(r.token.start)
        r = next_r
      return r
    name = f"({left._name}>>{right._name})"
    return Parser(m, name, loc)

  def __rshift__(self, other):
    loc = Parser._get_loc()
    other = Parser._to_parser(other, loc)
    return Parser.__rshift__internal(self, other, loc)

  def __rrshift__(self, other):
    loc = Parser._get_loc()
    other = Parser._to_parser(other, loc)
    return Parser.__rshift__internal(other, self, loc)

  @staticmethod
  def __lshift__internal(left, right, loc):
    name = f"({left._name}<<{right._name})"
    def m(s):
      r = left(s)
      if r:
        next_r = right(s)
        if next_r:
          r._token = r._token.set_end(next_r.token.end)
        else:
          r = next_r
      return r
    return Parser(m, name, loc)

  def __lshift__(self, other):
    loc = Parser._get_loc()
    other = Parser._to_parser(other, loc)
    return Parser.__lshift__internal(self, other, loc)

  def __rlshift__(self, other):
    loc = Parser._get_loc()
    other = Parser._to_parser(other, loc)
    return Parser.__lshift__internal(other, self, loc)

  def __getitem__(self, name):
    loc = Parser._get_loc()
    p = Parser(self, name, loc)
    p.name = name
    p._processor = ResultProcessor(self._processor)
    return p

  def __pos__(self):
    loc = Parser._get_loc()
    name = f"+({self._name})"
    def m(s):
      result = Result()
      r = self(s)
      while r:
        if not result:
          result = r
          result.value = [r.value] if r.value else []
        r = self(s)
        if r:
          if r.value is not None:
            result.value.append(r.value)
          result._token = result._token.set_end(r.token.end)
      return result
    return Parser(m, name, loc)

  def __mod__(self, p):
    loc = Parser._get_loc()
    if type(p) is tuple:
      process, pname = p
    else:
      process = p
      pname = p.__name__
      if '__code__' in dir(p):
        pfname = p.__code__.co_filename
        pline = p.__code__.co_firstlineno
        pname = f"{pname}@{pfname}:{pline}"
    name = f"{self.name}%{pname}"
    parser = Parser(self, name, loc)
    processor = self._processor % (process, pname,)
    parser._processor = processor
    parser.name = name
    return parser

  def __floordiv__(self, c):
    loc = Parser._get_loc()
    if type(c) is tuple:
      check, cname = c
    else:
      check = c
      cname = c.__name__
      if '__code__' in dir(c):
        cfname = c.__code__.co_filename
        cline = c.__code__.co_firstlineno
        cname = f"{cname}@{cfname}:{cline}"
    name = f"{self.name}//{cname}"
    parser = Parser(self, name, loc)
    processor = self._processor // (check, cname,)
    parser._processor = processor
    parser.name = name
    return parser

  def __rpow__(self, other):
    if not isinstance(other, dict):
      raise ValueError("dict expected")
    loc = Parser._get_loc()
    overrides = {k: Parser._to_parser(v, loc) if isinstance(k, Parser) else v for k,v in other.items()}
    name = f"({overrides}**{self.name})"
    def m(s):
      s.context.local.update(overrides)
      return self(s)
    return Parser(m, name, loc)

### UTILS ###

def parser_gen(gen_fn):
  def new_gen(*args, **kwargs):
    fr, filename, line, fname, lines, pos = \
        inspect.getouterframes(inspect.currentframe())[1]
    loc = f"{filename}:{line}"
    p = gen_fn(*args, **kwargs)
    if isinstance(p, Parser):
      parser = p
    else:
      repr_args = ", ".join([repr(a) for a in args])
      name = f"{gen_fn.__name__}({repr_args})"
      parser = Parser(p, name)
    parser.loc = loc
    return parser
  return new_gen

def parser(fn):
  fr, filename, line, fname, lines, pos = \
    inspect.getouterframes(inspect.currentframe())[1]
  name = f"{fn.__name__}"
  loc = f"{filename}:{line}"
  parser = Parser(fn, name, loc)
  return parser

@parser_gen
def regexp(re_string):
  return Parser(re.compile(re_string))

@parser_gen
def term(t):
  return Parser(t)

@parser_gen
def overload(p):
  def m(s):
    return s.context.get(p, p)(s)
  return Parser(m, "!"+p.name+"!")

comm_lisp          = regexp(';[^\n]*\n')                  ['comment ; .. \n']
comm_c_line        = regexp('//[^\n]*\n')                 ['comment //..\n']
comm_c_multiline   = regexp('/\\*([^*]|\\*[^/])*\\*/')    ['comment /*...*/']
comm_tla_line      = regexp('\\\\\\*[^\n]*\n')            ['comment \\*..\n']
comm_tla_multiline = regexp('\\(\\*([^*]|\\*[^)])*\\*\\)')['comment (*...*)']
comment = (comm_lisp        |
           comm_c_line      |
           comm_c_multiline |
           comm_tla_line    |
           comm_tla_multiline) ['comment']

blankchars = regexp("\\s*")['whitespace']
whitespace = (overload(comment) | overload(blankchars))['whitespace']
ws = overload(whitespace) ['ws']

br_open  = term("(")['br_open']
br_close = term(")")['br_close']
chop_ends = (lambda v: v[1:-1] if isinstance(v, collections.abc.Sequence) else v, "chop_ends")

@parser_gen
def in_brackets(p):
  return (ws >> overload(br_open) >> ws >> p << ws << overload(br_close) << ws)[f"'('{p.name}')'"]

string_sq = regexp('\'([^\']|\\\\[^\'])*\'')     ['string_sq']
string_dq = regexp('"([^"]|\\\\[^"])*"')         ['string_dq']
string_q  = (string_sq | string_dq)              ['string_q']
string    = ((ws >> string_q << ws) % chop_ends) ['string']

identifier = (ws >> regexp("[a-zA-Z_][a-zA-Z0-9_]*") << ws)['identifier']
@parser_gen
def keyword(kw): 
  return (ws >> term(kw) << ws)[f"keyword('{kw}')"]

# TODO: literal can include brackets or not?
literal = regexp("\\S+")['literal']

non_neg = ((lambda v: v >= 0), 'non-neg')
positive = ((lambda v: v >0) , 'positive')

intnum = ((ws >> regexp("[+-]?[0-9_]*[0-9]") << ws)['intnum_s'] % int)['intnum']
natnum = (intnum // non_neg)['natnum']
nznatnum = (intnum // positive)['nznatnum']

#TODO
flpnum = None
fxpnum = None
ratnum = None
cnum   = None

@parser_gen
def value(v):
  return (term("") % (lambda _: v))[f"value({repr(v)})"]

# checks
def check_exact_dict(d):
  # all keys are inhabited and only one item per key
  return all(len(v) == 1 for v in d.values())

def check_dict(d):
  # all keys are inhabited and only one item per key
  return all(len(v) <= 1 for v in d.values())

def unwrap_dict(d):
  return {k: None if len(v) == 0 else v[0] for k,v in d.items()}

