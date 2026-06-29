from collections import namedtuple
import inspect
import re

import shutil
terminal_columns = shutil.get_terminal_size((80,25)).columns

# TODO: add to log and bt - parameter slice from:to
# TODO: single numeration of items in bt, log and context log
# TODO: better naming for lambdas in parser names
# TODO: breakpoints to Stream, watchpoints to Context

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

class Format:
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
    ns = f"{past_r}{'⮞' if zero_pos >=0 else ''}{future_r}"
    return ns

  @staticmethod
  def Table(hdr, data, start = None, end = None, total_width=terminal_columns-4):
    # hdr = [(name, ratio for max width/zero - rest, shortener fn), ...]
    # todo: ratio < 0 - is fixed width
    # data = tuples of strings/lambda(width) closure
    # . XXX | XXX | XXXX .
    sum_width = total_width - 3*(len(hdr)-1) - 2
    lens = tuple(len(elt[0]) for elt in hdr)
    def get_len(item):
      if isinstance(item, str):
        return len(item)
      return sum_width
    [lens := tuple(max(get_len(row[i]), lens[i]) for i in range(len(lens))) for row in data]
    lens = tuple(min(lens[i], int(hdr[i][1] * sum_width)) for i in range(len(lens)))
    if 0 in lens:
      zeros = sum(l == 0 for l in lens)
      zw = int((sum_width - sum(lens)) / zeros)
      lens = tuple(l or zw for l in lens)
    delta = sum(lens) - sum_width
    max_idx = lens.index(max(lens))
    lens = list(lens)
    lens[max_idx] -= delta
    lens = tuple(lens)
    def get_str(shortener, data, width):
      if isinstance(data, str):
        return shortener(data, width)
      return shortener(data(width), width)
    data = [tuple(get_str(hdr[i][2], row[i], lens[i]) for i in range(len(lens))) for row in data]
    lines = ["━"*(l+2) for l in lens]
    top = "┯".join(lines)
    sep = "╪".join(["═"*(l+2) for l in lens])
    bot = "┷".join(lines)
    dashed = "│".join([f"{'*'*min(3, l):^{l+2}}" for l in lens])
    def line(vals):
      fields = (f" {hdr[i][2](vals[i], lens[i]):<{lens[i]}} " for i in range(len(lens)))
      return "│".join(fields)
    text  = top
    text += "\n" + "│".join([f" {hdr[i][0]:<{lens[i]}} " for i in range(len(lens))])
    text += "\n" + sep
    start = start or 0
    end = end or len(data)
    if start < 0:
      start = len(data) + start
    start = max(0, start)
    if end < 0:
      end = len(data) + end
    end = min(len(data), end)
    if start > 0 :
      text += "\n" + dashed
    for i in range(start, end):
      text += "\n" + line(data[i])
    if end < len(data):
      text += "\n" + dashed
    text += "\n" + bot
    return text
    
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
    line = Format.Part(self.stream.data, self.start, 20)
    parser_name = Format.Shorten(repr(self.parser), 30)
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

class LoggedDict:
  def __init__(self, dict, log):
    self._log = log
    self._dict = dict

  def get(self, idx, default = None):
    v = self._dict.get(idx, self)
    if v is self:
      self._log(('get', idx, "N/A" if default is self else f"N/A ({default})",))
      v = default
    else:
      self._log(('get', idx, v,))
    return v

  def __getitem__(self, idx):
    v = self.get(idx, self)
    if v is self:
      raise KeyError(idx)
    return v

  def __setitem__(self, idx, val):
    self._log(('set', idx, val,))
    self._dict.__setitem__(idx, val)

  def __delitem__(self, idx):
    self._log(('del', idx, None,))
    self._dict.__delitem__(idx)
      
  def listing(self):
    shorten_mid = lambda v, w: Format.Shorten(v, w)
    hdr = (('key',0,shorten_mid),
           ('value',0,shorten_mid))
    data = [ (repr(key), repr(val)) for key, val in self._dict.items() ]
    return Format.Table(hdr, data)

  def __repr__(self):
    return self.listing()

class MemoStack:
  def __init__(self):
    self._stack = []
    self._stack_idx = 0
  def push(self, item):
    if self._stack_idx >= len(self._stack):
      self._stack.append(item)
    else:
      self._stack[self._stack_idx] = item
    self._stack_idx += 1
  def pop(self):
    self._stack_idx -= 1
    assert self._stack_idx >= 0, "Error  push()/pop() mismatch!"
    return self._stack[self._stack_idx]
  def pop_and_cut(self):
    self._stack_idx -= 1
    item = self._stack[self._stack_idx]
    self._stack = self._stack[0:self._stack_idx]
    return item
  @property
  def sp(self):
    return self._stack_idx
  def clear(self):
    self._stack = []
    self._stack_idx = 0
  def __getitem__(self, idx):
    return self._stack[idx]
  def __setitem__(self, idx, val):
    self._stack[idx] = val
  @property
  def valid_range(self):
    return range(0,self.sp)
  @property
  def all_range(self):
    return range(0, len(self._stack))

class Context:
  class Watchpoint:
    # on_change: parser, scope, frameN,key, old_value, new_value
    # on_read: parser, scope, frameN, key, value
    # on_key_missed: parser, scope, key 
    pass

  def __init__(self, ctx = None, debug = False):
    self._top = ctx or dict()
    self._stack = MemoStack()
    self._log = []
    self._debug = debug

  def clear(self):
    self._stack.clear()
    self._log.clear()

  def push(self, parser):
    self._stack.push([parser, dict()])

  def pop(self):
    self._stack.pop()
  
  def advance(self):
    self._stack.pop_and_cut()

  def _logger(self, tag):
    def log_fn(data):
      data = (self.parser(), tag) + data
      self._log.append(data)
    return log_fn
    
  def _frame(self, n=-1):
    if n < 0:
      n += self._stack.sp
    if 0 <= n < self._stack.sp:
      return self._stack[n][1]
    return None

  def frame(self, n=-1):
    frame = self._frame(n)
    if frame is None:
      return None
    if self._debug:
      if n < 0:
        n += self._stack.sp
      return LoggedDict(frame, self._logger(f"frame({n})"))
    return frame
    
  def parser(self, n=-1):
    if n < 0:
      n += self._stack.sp
    if 0 <= n < self._stack.sp:
      return self._stack[n][0]
    return None
     
  @property
  def top(self):
    if self._debug:
      return LoggedDict(self._top, self._logger('top'))
    return self._top

  class lookup:
    def __init__(self, ctx):
      self.__ctx = ctx

    def get(self, idx, default=None):
      if self.__ctx._stack.sp > 0:
        for i in range(self.__ctx._stack.sp-2, -1, -1):
          if idx in self.__ctx._frame(i):
            return self.__ctx._frame(i)[idx]
      return self.__ctx._top.get(idx, default)
    
    def __getitem__(self, idx):
      v = self.get(idx, self)
      if v is self:
        raise KeyError(idx)
      return v

  @property
  def _upper(self):
    return Context.lookup(self)
  
  @property
  def upper(self):
    if self._debug:
      return LoggedDict(self._upper, self._logger('upper'))
    return self._upper
   
  @property
  def local(self):
    l = self._frame()
    if l is None:
      return None
    if self._debug:
      return LoggedDict(l, self._logger('local'))
    return l

  def __getitem__(self, key):
    local = self._frame()
    if local and key in local:
      return local[key]
    return self.upper[key]

  def get(self, key, default=None):
    local = self._frame()
    if local and key in local:
      return local[key]
    return self.upper.get(key, default)

  def __setitem__(self, key, val):
    self.local[key] = val

  def __delitem__(self, key):
    del self.local[key]

  def log(self, start=None, end=None):
    if not self._debug:
      return "Context log is disabled."
    data = [ (str(n+1),
              repr(pars.name)[1:-1],
              pars.loc,
              tag,
              op,
              repr(key),
              repr(val))
             for n, (pars, tag, op, key, val) in enumerate(self._log)]
    shorten_mid = lambda v, w: Format.Shorten(v, w)
    shorten_left = lambda v, w: Format.Shorten(v,w,0)
    iden = lambda v, w: v
    hdr = (('N', 0.1, iden),
           ('parser', 0.3, shorten_mid),
           ('defined at', 0.2 , shorten_left),
           ('scope', 0.1, iden),
           ('OP',0.1, iden),
           ('key',0, shorten_mid),
           ('value',0, shorten_mid))
    return "Stream context log\n" + Format.Table(hdr, data, start, end)
    
  def listing(self, start=None, end=None):
    data = [ ((">" if n == self._stack.sp-1 else "") + str(n+1),
              repr(pars.name)[1:-1],
              pars.loc,
              repr(dict))
             for n, (pars, dict) in enumerate(self._stack._stack)]
    shorten_mid = lambda v, w: Format.Shorten(v, w)
    shorten_left = lambda v, w: Format.Shorten(v,w,0)
    iden = lambda v, w: v
    hdr = (('N', 0.1, iden),
           ('parser', 0.3, shorten_mid),
           ('defined at', 0.2 , shorten_left),
           ('frame', 0, iden))
    top = f"Toplevel : {shorten_mid(repr(self._top), terminal_columns-4)}\n"
    return "Stream context frames\n" + top + Format.Table(hdr, data, start, end)

  def __repr__(self):
    return self.log() + "\n" + self.listing()

class Breakpoints:
  def __init__(self, stream):
    self._stream = stream
    self._bp = []

  def add(self, parser=None, invocations=None, pos=None):
    if pos is None:
      pos = self._stream.pos
    if type(pos) is int:
      pos = slice(pos,len(self._stream.data)) # or pos + 1?
    self._bp.append([parser, 0, invocations, pos])

  def __call__(self, parser, invocations = None, pos=None):
    self.add(parser, invocations, pos)
    
  class _adder_remover:
    def __init__(self, parent, idx):
      self._parent = parent
      self._idx = idx
    def __call__(self, parser = None, invocations = 1):
      if parser is None:
        self._parent.add(None, None, self._idx)
      assert type(invocations) is int
      self._parent.add(parser, invocations, self._idx)
    def __delitem__(self):
      self._parent.rm_pos(self._idx)

  def __getitem__(self, idx):
    return Breakpoints._adder_remover(self, idx)
      
  def __delitem__(self, idx):
    self.rm_pos(idx)

  def rm(self, n):
    del self._bp[n-1]

  def rm_pos(self, idx):
    removed = True
    if type(idx) is int:
      idx = slice(idx,len(self._stream.data))
    while removed:
      removed = False
      for i in range(len(self._bp)):
        pos = self._bp[i][3]
        if pos.start >= idx.start and pos.stop <= idx.stop:
          del self._bp[i]
          break

  def reset(self):
    for i in range(len(self._bp)):
      self._bp[i][1] = 0

  def clear(self):
    self._bp.clear()

  def check(self, parser):
    for i in range(len(self._bp)):
      pars, cntr, invoc, pos = self._bp[i]
      if parser == pars:
        cntr += 1
        self._bp[i][1] = cntr
        if cntr >= invoc and pos.start <= self._stream.pos < pos.stop:
          self._bp[i][1] = 0
          return i
    for i in range(len(self._bp)):
      pars, cntr, invoc, pos = self._bp[i]
      if pars is None and pos.start <= self._stream.pos < pos.stop:
        return i
    return None

  def from_log(self, n):
    n-=1
    assert 0 <= n < len(self._stream._log)
    depth, pos, pars, action = self._stream._log[n]
    self.add(pars, 1, pos)
    
  def from_bt(self, n):
    n-=1
    assert 0 <= n < len(self._stream._bt)
    pos, pars = self._stream._bt[n]
    self.add(pars, 1, pos)
      
  def listing(self, start=None, end=None, bp_hit=-1):
    shorten_mid = lambda v, w: Format.Shorten(v, w)
    shorten_left = lambda v, w: Format.Shorten(v,w,0)
    iden = lambda v, w: v
    hdr = (('N', 0.1, iden),
           ('parser', 0.3, shorten_mid),
           ('defined at', 0.2 , shorten_left),
           ('calls', 0.1, iden),
           ('pos', 0.1, iden),
           ('triggers at input', 0, shorten_mid))
    data = [ ((">" if n == bp_hit else "") + str(n+1),
              repr(pars.name)[1:-1] if pars is not None else "---",
              pars.loc if pars is not None else "---",
              (f"{cntr} < {max_cntr}" if cntr < max_cntr else
              f"{cntr} == {max_cntr}" if cntr == max_cntr else
              f"{cntr} > {max_cntr}") if type(cntr) is int and type(max_cntr) is int
              else "---",
              f"[{pos.start}:{pos.stop}]",
              (lambda pos: \
               lambda w: Format.Part(self._stream.data, pos.start, pos.stop - pos.start))(pos))
             for n,(pars, cntr, max_cntr, pos) in enumerate(self._bp)]
    return "Breakpoints\n" + Format.Table(hdr, data, start, end)

  def __repr__(self):
    return self.listing()
    
class Stream():      
  def __init__(self, data, context = None, debug = False):
    self._data = data
    self._debug = debug
    self._stack = MemoStack()
    self._context = Context(context, debug)
    self._bp = Breakpoints(self)
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

  @property
  def bp(self):
    return self._bp
  
  @property
  def rest(self):
    return Format.Part(self.data, self.pos, terminal_columns, 10)

  def rewind(self):
    self._pos = 0
    self._log = []
    self._stack.clear()
    self.context.clear()
    self.bp.reset()

  def push(self, parser):
    self._context.push(parser)
    if self._debug:
      self._log.append((self._stack.sp,self.pos, parser, 'v',))
      self._stack.push((self.pos, parser,))
      bp_hit = self._bp.check(parser)
      if bp_hit is not None:
        text = f"Breakpoint {bp_hit + 1} is hit\n"
        text += self.backtrace(start=-5) + "\n"
        text += self.log(start=-5) + "\n"
        text += self.context.listing(start=-5) + "\n"
        text += self.context.log(start=-5) + "\n"
        text += self.bp.listing(start=min(0, bp_hit-2), end=bp_hit+2, bp_hit=bp_hit) + "\n"
        text += "\npredefined objects:"
        text += f"\nparser - {parser}"
        text += f"\nstream - {Format.Part(self.data, self.pos, 20, 5)}"
        text += f"\nctx    - context"
        text += f"\nbp     - breakpoints"
        text += "\nYou are droppend in PDB now\n"
        print(text)
        stream = self
        ctx = stream.context
        bp = stream.bp
        breakpoint()

  def pop(self):
    self._context.pop()
    if self._debug:
      self.pos, parser = self._stack.pop()
      self._log.append((self._stack.sp,self.pos, parser, '^',))

  def advance(self):
    self._context.advance()
    if self._debug:
      # just cut stack, position is kept
      _pos, parser = self._stack.pop_and_cut()
      self._log.append((self._stack.sp, self.pos, parser, '>',))

  def log(self, start=None, end=None):
    if not self._debug:
      return "Stream debug is disabled."
    calls = dict()
    def get_calls(parser, action):
      n = calls.get(parser, 0)
      if action == 'v':
        n += 1
      calls[parser] = n
      return n 
    data = [ (str(n+1),
              str(depth),
              str(get_calls(pars, action)),
              action,
              repr(pars.name)[1:-1],
              pars.loc,
              (lambda pos: lambda w: Format.Part(self.data, pos, w, 5))(pos))
             for n, (depth, pos, pars, action) in enumerate(self._log)]
    shorten_mid = lambda v, w: Format.Shorten(v, w)
    shorten_left = lambda v, w: Format.Shorten(v,w,0)
    iden = lambda v, w: v
    hdr = (('N', 0.1, iden),
           ('depth', 0.1, iden),
           ('calls', 0.1, iden),
           ('action', 0.1, iden),
           ('parser', 0.3, shorten_mid),
           ('defined at', 0.2 , shorten_left),
           ('parser input', 0, iden))
    return "Parsing log\n" + Format.Table(hdr, data, start, end)

  def backtrace(self, start=None, end=None):
    # TODO: add info from context, link context log, bt, and log via single numeration
    if not self._debug:
      return "Stream debug is disabled.\n"
    s = Format.Part(self.data, self.pos, terminal_columns-9, 10)
    text =  f"Parsing backtrace\n{'━'*(terminal_columns-4)}\n"
    text += f"input: {s}\n"
    data = [ ((">" if n == self._stack.sp-1 else "") + str(n+1),
              repr(pars.name)[1:-1],
              pars.loc,
              (lambda pos: lambda w: Format.Part(self.data, pos, w, 5))(pos))
             for n, (pos, pars) in enumerate(self._stack._stack)]
    shorten_mid = lambda v, w: Format.Shorten(v, w)
    shorten_left = lambda v, w: Format.Shorten(v,w,0)
    iden = lambda v, w: v
    hdr = (('N', 0.1, iden),
           ('parser', 0.3, shorten_mid),
           ('defined at', 0.2 , shorten_left),
           ('parser input', 0, iden))
    return text + Format.Table(hdr, data, start, end)

  @property
  def bt(self):
    print(self.backtrace())

  @property
  def lg(self):
    print(self.log())

  def __repr__(self):
    bt = self.backtrace()
    log = self.log()
    ctx_log = repr(self.context)
    bp = repr(self.bp)
    return f"{bt}\n{log}\n{ctx_log}\n{self.bp}\n"

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

  def replace(self, new_parser):
    loc = Parser._get_loc()
    parser = Parser._to_parser(new_parser, loc)
    self.__init__(parser, loc=loc)
    return self
    
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
      for k,v in overrides.items():
        s.context.local[k]=v
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

