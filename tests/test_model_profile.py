import unittest
from scripts.check_ax_template import validate_context


class ModelProfileTest(unittest.TestCase):
    def setUp(self):
        self.tokens=['']*30
        for i,text in {25:'<|im_start|>',27:'<|im_end|>',9:'<|system|>',8:'<|user|>',10:'<|assistant|>'}.items():
            self.tokens[i]=text
        self.context=[25,9,1,27,25,8,2,27,25,10,3]

    def test_exact_role_rendering_passes(self):
        validate_context(self.tokens,self.context)

    def test_wrong_roles_duplicates_missing_prefix_and_invalid_ids_fail(self):
        for context in ([25,1,27,25,2,27,25,3],self.context+self.context,None,
                        self.context[:-3],self.context+[999],self.context+[True]):
            with self.subTest(context=context),self.assertRaises(ValueError):
                validate_context(self.tokens,context)
        with self.assertRaises(ValueError):validate_context(['']*30,self.context)


if __name__=='__main__':unittest.main()
