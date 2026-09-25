import unittest
from string_utils import reverse_string

class TestStringUtils(unittest.TestCase):
    
    def test_reverse_normal_string(self):
        self.assertEqual(reverse_string('hello'), 'olleh')
        
    def test_reverse_string_with_spaces(self):
        self.assertEqual(reverse_string('hello world'), 'dlrow olleh')
        
    def test_reverse_empty_string(self):
        self.assertEqual(reverse_string(''), '')

if __name__ == '__main__':
    unittest.main()