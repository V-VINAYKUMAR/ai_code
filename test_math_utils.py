import unittest
from math_utils import calculate_average

class TestMathUtils(unittest.TestCase):

    def test_calculate_average_normal_numbers(self):
        """Test calculation of average with a standard list of integers."""
        numbers = [10, 20, 30, 40, 50]
        expected = 30.0
        self.assertEqual(calculate_average(numbers), expected)

    def test_calculate_average_decimal_numbers(self):
        """Test calculation of average with floating-point numbers."""
        numbers = [1.5, 2.5, 3.5]
        expected = 2.5
        self.assertEqual(calculate_average(numbers), expected)

    def test_calculate_average_empty_list(self):
        """Test calculation of average with an empty list."""
        numbers = []
        expected = 0.0
        self.assertEqual(calculate_average(numbers), expected)


if __name__ == "__main__":
    unittest.main()