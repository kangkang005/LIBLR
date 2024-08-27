import sys
import pprint
import LIBLR

from LIBLR import cstring

class LibertyAction:

    def get_dict(self, rule ,args):
        return {args[1] : args[3]}

    def get_function(self, rule ,args):
        return {
            "_name"         : args[1],
            "_argument"     : args[3],
            "_dictionary"   : args[5],
        }

    def get_null(self, rule, args):
        return None

    def get_function_field(self, rule, args):
        return args[2]

    def key_datum_many(self, rule, args):
        return args[1] + [args[2]]

    def key_datum_one(self, rule, args):
        return [args[1]]

    def list_empty(self, rule, args):
        return []

    def list_one(self, rule, args):
        return [args[1]]

    def list_many(self, rule, args):
        return args[1] + [args[3]]

    def get1(self, rule, args):
        return args[1]

    def get_string(self, rule, args):
        return cstring.string_unquote(args[1])

    def get_number(self, rule, args):
        text = args[1]
        v = float(text)
        if v.is_integer():
            return int(v)
        return v

parser = LIBLR.create_parser_from_file('grammar/liberty.ebnf',
                                       LibertyAction(),
                                    #    algorithm = 'lalr',
                                       algorithm = 'lr1',
                                       )
text = open('sample/sample.lib').read()

pprint.pprint(parser(text))