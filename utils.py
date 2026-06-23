from cp import *
import collections

@parser_gen
def regexp(re_string):
  return Parser(re.compile(re_string))

@parser_gen
def term(t):
  return Parser(t)

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

whitespace = regexp("\\s*")['whitespace']
ws = -((comment | whitespace))['ws']

br_open  = (ws >> "(" << ws)['"("']
br_close = (ws >> ")" << ws)['")"']
chop_ends = (lambda v: v[1:-1] if isinstance(v, collections.abc.Sequence) else v, "chop_ends")

@parser_gen
def in_brackets(p):
  return (br_open >> p << br_close)[f"'('{p.name}')'"]

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

