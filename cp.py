# TODO:
# *1. special class for buffer
# *2. special class for parser result (monadic style)
# *3. special class for result transformers
# *4. names for parsers (for diagnostics)
# *5. backtrace
#  6. better error reporting:
#     user-defined parsers and checkers should have ability to return messages
#  7. user context passing
#  8. tests!!!
#  9. docs!!!
#  10. refactoring:
#      - Split Parser into several classes
#      - better naming
#      - readability!
#      - move code for diagnostics message and formatting into separate functions


from collections import namedtuple
import inspect
import re


# text formatting helpers
def _shorten_str(s, w, ratio=0.5):
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

def _line_with_pos(s, pos, width, zero_pos = 5):
  start = pos - zero_pos if pos > zero_pos else 0
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
  ns = f"{past_r}🢂◈{future_r}"
  return ns

# token to be attached to Result
class Token(namedtuple('Token', ['stream', 'parser_name', 'start', 'end'])):
  __slots__=()
  def set_name(self, name):
    return Token(self.stream, name, self.start, self.end)
  @property
  def text(self):
    return repr(self.stream.data[self.start:self.end])[1:-1]
  def __repr__(self):
    return f"Token('{_line_with_pos(self.stream.data, self.start, 20, )}', {_shorten_str(repr(self.parser_name)[1:-1], 30)}, {self.start}, {self.end})"
  @staticmethod
  def default(stream, parser_name):
    return Token(stream, parser_name, stream.pos, stream.pos)

# Parsing result
# .value - holds processed result
# .token - holds token, corresponding to result
# ._err_msg - holds error message, if some processors/checkers failed
class Result:
  def __init__(self, *args, **kw):
    self._token = None
    if len(args) == 1 and len(kw) == 0 and isinstance(args[0], Token):
      self._token = args[0]
    elif len(args) != 0 or len(kw) != 0:
      self._token = Token(*args, **kw)
    self._value = self._token
    self._err_msg = None
    if self._value:
      stream, _pname, start, end = self._value
      self._value = stream.data[start:end]

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
  def parser_name(self):
    if self._token:
      return self._token.parser_name
    return None

  @parser_name.setter
  def parser_name(self, name):
    if self._token:
      self._token = self._token.set_name(name)

  @property
  def value(self):
    return self._value

  @value.setter
  def value(self, val):
    self._value = val

  def __repr__(self):
    if self:
      val = repr(self._value)
      parser = repr(self._token.parser_name)[1:-1]
      text = f"{val}" + \
            (f" ('{parser}'@'{self._token.text}'@[{self._token.start}:{self._token.end}])" if self._token else "")
    else:
      text = f"<INVALID>\n{self._err_msg or ''}"
    return text

#Result processor for holding pipeline of processors and checkers
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
      if t == 0:
        try:
          v.value = p(v.value)
        except Exception as err:
          text =  f"Processing '{repr(n)[1:-1]}' failed on value {repr(v.value)}\n"
          text += f"Exception {err=}, {type(err)=}\n"
          text += f"Token: ... {v.token.text} ...\n"
          text += f"Stream:\n"
          text += repr(v.token.stream)
          v.invalidate(text)
      elif t == 1:
        if not p(v.value):
          text = f"Check '{repr(n)[1:-1]}' failed on value {repr(v.value)}\n"
          text += f"Token: ... {v.token.text} ...\n"
          text += f"Stream:\n"
          text += repr(v.token.stream)
          v.invalidate(text)
      else:
        raise ValueError("Internal error in ResultProcessor")
    return v

class Stream():
  # TODO: function to get residual
  def __init__(self, data, bt_enabled = False, log_enabled = False):
    self._data = data
    self._bt_enabled = bt_enabled
    self._log_enabled = log_enabled
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

  def rewind(self):
    self._pos = 0
    self._log = []
    self._stack = []
    self._stack_idx = 0

  def push(self, parser):
    if self._log_enabled:
      self._log.append((self._stack_idx,self.pos, parser))
    if self._bt_enabled:
      if self._stack_idx >= len(self._stack):
        self._stack.append((self.pos, parser,))
      else: self._stack[self._stack_idx] = (self.pos, parser,)
      self._stack_idx += 1

  def pop(self):
    if self._bt_enabled:
      self._stack_idx -= 1
      assert self._stack_idx >= 0, "Error stream push()/pop() mismatch!"
      self.pos, _p = self._stack[self._stack_idx]

  def advance(self):
    if self._bt_enabled:
      # just cut stack, position is kept
      self._stack = self._stack[0:self._stack_idx]
      self._stack_idx -= 1

  def __repr__log(self):
    if not self._bt_enabled:
      return "Stream log is disabled."
    total_width = 120
    depth_width = 5
    name_width = max([len("parser")] + [len(pars.name) for d,pos,pars in self._log]) + 1
    loc_width = max([len("defined at")] + [len(pars.loc) for d,pos,pars in self._log]) + 1
    if name_width > 30:
      name_width = 30
    if loc_width > 20:
      loc_width = 20

    log_input_width = total_width - depth_width - name_width - loc_width - 7

    def log_line(depth, pos, name, loc):
      l = _line_with_pos(self.data, pos, log_input_width-3, 5)
      name = _shorten_str(repr(name)[1:-1], name_width)
      loc = _shorten_str(loc, loc_width, 0)
      return f"{depth:<{depth_width}} │ {name:<{name_width}} │ {loc:<{loc_width}} │ {l}"

    s = _line_with_pos(self.data, self.pos, total_width-9, 10)
    text  = f"Parsing log\n"
    text += f"{'━'*depth_width}━┯━{'━'*name_width}━┯━{'━'*loc_width}━┯{'━'*log_input_width}\n"
    text += f"{'depth':<{depth_width}} │ {'parser':<{name_width}} │ {'defined at':<{loc_width}} │ parser input\n"
    text += f"{'═'*depth_width}═╪═{'═'*name_width}═╪═{'═'*loc_width}═╪{'═'*log_input_width}"
    for depth, pos, par in self._log:
      text += "\n" + log_line(depth, pos, par.name, par.loc)
    text +=  f"\n{'━'*depth_width}━┷━{'━'*name_width}━┷━{'━'*loc_width}━┷{'━'*log_input_width}\n"
    return text

  def __repr__bt(self):
    if not self._bt_enabled:
      return "Stream backtrace is disabled.\n"
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
      l = _line_with_pos(self.data, pos, bt_input_width-3, 5)
      name = _shorten_str(repr(name)[1:-1], name_width)
      loc = _shorten_str(loc, loc_width, 0)
      return f"{name:<{name_width}} │ {loc:<{loc_width}} │ {l}"

    s = _line_with_pos(self.data, self.pos, total_width-9, 10)
    text =  f"Parsing backtrase\n{'━'*total_width}\n"
    text += f"input ⮞ {s}\n{'━'*name_width}━┯━{'━'*loc_width}━┯{'━'*bt_input_width}\n"
    text += f"{'parser':<{name_width}} │ {'defined at':<{loc_width}} │ parser input\n"
    text += f"{'═'*name_width}═╪═{'═'*loc_width}═╪{'═'*bt_input_width}"
    for pos, par in self._stack:
      text += "\n" + bt_line(pos,par.name, par.loc)
    text +=  f"\n{'━'*name_width}━┷━{'━'*loc_width}━┷{'━'*bt_input_width}\n"
    return text

  def __repr__(self):
    bt = self.__repr__bt()
    log = self.__repr__log()
    return f"{bt}\n{log}\n"


class Parser:
  @staticmethod
  def _is_lambda_wrapper(l):
    result = False
    try:
      if callable(l):
        if l.__code__.co_argcount == 0:
          result = True
    except:
      pass
    return result

  @staticmethod
  def _possible_unwrap(l):
    if Parser._is_lambda_wrapper(l):
      return l()
    return l

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
    match = True
    while match:
      match = False
      for k,p in self._parser.items():
        r = p(s)
        if r:
          match = True
          if not result:
            result = r
            result.value = {k:[] for k in self._parser}
          result._token = Token(result.token.stream,
                            self.name,
                            result.token.start,
                            r.token.end)
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
        result._token = Token(result.token.stream,
                              self.name,
                              result.token.start,
                              r.token.end)
    if result:
      result.value = type(self._parser)(*result.value)
    return result

  def __call__tuple(self, s):
    for p in self._parser:
      r = p(s)
      if r:
        r._token = Token(r.token.stream,
                         self.name,
                         r.token.start,
                         r.token.end)
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
        result._token = Token(result.token.stream,
                              self.name,
                              result.token.start,
                              r.token.end)
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
      s = Stream(s, bt_enabled = True, log_enabled = True)
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
    r.parser_name = self.name
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
    return self._processor(r)

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
    p = Parser(m, name, loc)
    return p

  def __invert__(self):
    loc = Parser._get_loc()
    name = f"~({self._name})"
    def m(s):
      r = self(s)
      if not r:
        r = Result(s, '', s.pos, s.pos)
        r.value = None
      return r
    p = Parser(m, name, loc)
    return p

  def __truediv__(self, val):
    loc = Parser._get_loc()
    name = f"(({self._name})/{val})"
    def m(s):
      r = self(s)
      if not r:
        r = Result(s, '', s.pos, s.pos)
        r.value = val
        # special case: lambda w/o args
        # treat it as self-ref to class being defined
        if Parser._is_lambda_wrapper(val):
          r.value = val()
      return r
    p = Parser(m, name, loc)
    return p

  def __eq__(self, val):
    loc = Parser._get_loc()
    name = f"(({self._name})=={val})"
    def m(s):
      r = self(s)
      if r:
        r.value = val
        # special case: lambda w/o args
        # treat it as self-ref to class being defined
        if Parser._is_lambda_wrapper(val):
          r.value = val()
      return r
    p = Parser(m, name, loc)
    return p

  def __rshift__(self, other):
    # parser drop, return next parser result
    # useful for prefix/suffix, etc
    # instead of:     in_brackets( (keyword('qwe') & p) unwrap)
    # more readable:  in_brackets('qwe' >> p)
    loc = Parser._get_loc()
    other = Parser._to_parser(other, loc)
    name = f"({self._name}>>{other._name})"
    def m(s):
      r = self(s)
      if r:
        next_r = other(s)
        if next_r:
          next_r._token = Token(s,
                            name,
                            r.token.start,
                            next_r.token.end)
        r = next_r
      return r
    p = Parser(m, name, loc)
    return p

  def __rrshift__(self, other):
    loc = Parser._get_loc()
    other = Parser._to_parser(other, loc)
    name = f"({other._name}>>{self._name})"
    def m(s):
      r = other(s)
      if r:
        next_r = self(s)
        if next_r:
          next_r._token = Token(s,
                            name,
                            r.token.start,
                            next_r.token.end)
        r = next_r
      return r
    p = Parser(m, name, loc)
    return p

  def __lshift__(self, other):
    # parser drop, return next parser result
    # useful for prefix/suffix, etc
    # instead of:     in_brackets( (keyword('qwe') & p) unwrap)
    # more readable:  in_brackets('qwe' >> p)
    loc = Parser._get_loc()
    other = Parser._to_parser(other, loc)
    name = f"({self._name}<<{other._name})"
    def m(s):
      r = self(s)
      if r:
        next_r = other(s)
        if next_r:
          r._token = Token(s,
                           name,
                           r.token.start,
                           next_r.token.end)
        else:
          r = next_r
      return r
    p = Parser(m, name, loc)
    return p

  def __rlshift__(self, other):
    # parser drop, return next parser result
    # useful for prefix/suffix, etc
    # instead of:     in_brackets( (keyword('qwe') & p) unwrap)
    # more readable:  in_brackets('qwe' >> p)
    loc = Parser._get_loc()
    other = Parser._to_parser(other, loc)
    name = f"({other._name}<<{self._name})"
    def m(s):
      r = other(s)
      if r:
        next_r = self(s)
        if next_r:
          r._token = Token(s,
                           name,
                           r.token.start,
                           next_r.token.end)
        else:
          r = next_r
      return r
    p = Parser(m, name, loc)
    return p

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
          result._token = Token(result.token.stream,
                                self.name,
                                result.token.start,
                                r.token.end)
      return result
    p = Parser(m, name, loc)
    return p

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

def parser_gen(gen_fn):
  def new_gen(*args, **kwargs):
    fr, filename, line, fname, lines, pos = \
        inspect.getouterframes(inspect.currentframe())[1]
    repr_args = ", ".join([repr(a) for a in args])
    name = f"{gen_fn.__name__}({repr_args})"
    loc = f"{filename}:{line}"
    p = gen_fn(*args, **kwargs)
    if isinstance(p, Parser):
      parser = p
    else:
      parser = Parser(p, name)
    parser.loc
    return parser
  return new_gen

def parser(fn):
  fr, filename, line, fname, lines, pos = \
    inspect.getouterframes(inspect.currentframe())[1]
  name = f"{fn.__name__}"
  loc = f"{filename}:{line}"
  parser = Parser(fn, name, loc)
  return parser
