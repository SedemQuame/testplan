"""
Class based assertions, these will be serialized into native dicts via marshmallow schemas.

An assertion object will call ``evaluate`` on instantiation and will
use the result of that call to set its ``passed`` attribute.
"""

import os
import re
import operator
import collections

import six
import lxml

from testplan.common.utils.convert import make_tuple, flatten_dict_comparison
from testplan.common.utils import comparison

from .base import BaseEntry, get_table


__all__ = [
    'Assertion',
    'RawAssertion',
    'IsTrue',
    'IsFalse',
    'Fail',
    'FuncAssertion',
    'Equal',
    'NotEqual',
    'Less',
    'LessEqual',
    'Greater',
    'GreaterEqual',
    'Contain',
    'NotContain',
    'RegexAssertion',
    'RegexMatch',
    'RegexMatchNotExists',
    'RegexSearch',
    'RegexSearchNotExists',
    'RegexFindIter',
    'RegexMatchLine',
    'ExceptionRaised',
    'EqualSlices',
    'EqualExcludeSlices',
    'ColumnContain',
    'TableMatch',
    'XMLCheck',
    'DictCheck',
    'DictMatch',
    'DictMatchAll',
    'FixCheck',
    'FixMatch',
    'FixMatchAll',
]


class Assertion(BaseEntry):

    meta_type = 'assertion'

    def __init__(self, description=None, category=None):
        super(Assertion, self).__init__(
            description=description, category=category)
        self.passed = bool(self.evaluate())

    def evaluate(self):
        raise NotImplementedError

    def __bool__(self):
        return self.passed

    __nonzero__ = __bool__


class RawAssertion(Assertion):
    """
      This class is used for creating explicit pass/fail entries
      with custom content.

      Its content will be displayed preformatted, so it's useful for
      integration with 3rd party testing libraries (unittest, qunit etc).
    """

    def __init__(self, passed, content, description=None, category=None):
        self._passed_override = passed
        self.content = content
        super(RawAssertion, self).__init__(
            description=description, category=category)

    def evaluate(self):
        return self._passed_override


class IsTrue(Assertion):

    def __init__(self, expr, description=None, category=None):
        self.expr = expr
        super(IsTrue, self).__init__(
            description=description, category=category)

    def evaluate(self):
        return bool(self.expr)


class IsFalse(IsTrue):

    def evaluate(self):
        return not bool(self.expr)


class Fail(Assertion):

    def evaluate(self):
        return False


class FuncAssertion(Assertion):

    func = None

    def __init__(self, first, second, description=None, category=None):
        self.first = first
        self.second = second
        super(FuncAssertion, self).__init__(
            description=description, category=category)

    def evaluate(self):
        return self.func(self.first, self.second)


class Equal(FuncAssertion):
    label = '=='
    func = operator.eq


class NotEqual(FuncAssertion):
    label = '!='
    func = operator.ne


class Less(FuncAssertion):
    label = '<'
    func = operator.lt


class LessEqual(FuncAssertion):
    label = '<='
    func = operator.le


class Greater(FuncAssertion):
    label = '>'
    func = operator.gt


class GreaterEqual(FuncAssertion):
    label = '>='
    func = operator.ge


class Contain(Assertion):

    def __init__(self, member, container, description=None, category=None):
        self.member = member
        self.container = container
        super(Contain, self).__init__(
            description=description, category=category)

    def evaluate(self):
        return self.member in self.container


class NotContain(Contain):

    def evaluate(self):
        return self.member not in self.container


class RegexAssertion(Assertion):

    def __init__(
        self, regexp, string, flags=0,
        description=None, category=None
    ):
        if isinstance(regexp, six.string_types):
            self.pattern = regexp
            self.regexp = re.compile(regexp, flags=flags)
        else:
            if flags != 0:
                raise ValueError(
                    '`flags` argument is redundant if'
                    ' `regexp` is of type `SRE.pattern`'
                )
            self.pattern = regexp.pattern
            self.regexp = regexp

        self.string = string
        self.match_indexes = []

        super(RegexAssertion, self).__init__(
            description=description, category=category)

    def get_regex_result(self):
        raise NotImplementedError

    def evaluate(self):
        result = self.get_regex_result()
        if result:
            self.match_indexes.append((result.start(), result.end()))
        return bool(result)


class RegexMatch(RegexAssertion):

    def get_regex_result(self):
        return self.regexp.match(self.string)


class RegexMatchNotExists(RegexMatch):

    def evaluate(self):
        return not super(RegexMatchNotExists, self).evaluate()


class RegexSearch(RegexAssertion):

    def get_regex_result(self):
        return self.regexp.search(self.string)


class RegexSearchNotExists(RegexSearch):

    def evaluate(self):
        return not super(RegexSearchNotExists, self).evaluate()


class RegexFindIter(RegexAssertion):

    def __init__(
        self, regexp, string, flags=0,
        condition=None, description=None, category=None
    ):
        self.condition = condition
        self.condition_match = None  # may be set by self.evaluate
        super(RegexFindIter, self).__init__(
            regexp, string, flags, description=description, category=category)

    def evaluate(self):
        result = list(self.regexp.finditer(self.string))

        for match in result:
            self.match_indexes.append((match.start(), match.end()))

        if self.condition:
            self.condition_match = self.condition(len(result))
            return bool(self.condition_match)

        return bool(result)


class RegexMatchLine(RegexAssertion):
    """
      Match indexes are a little bit different than other
      assertions for this one: (line_no, begin, end)
    """

    def evaluate(self):
        lines = self.string.split(os.linesep)
        for line_num, line in enumerate(lines):
            match = self.regexp.match(line)
            if match:
                self.match_indexes.append(
                    (line_num, match.start(), match.end()))
        return self.match_indexes


class ExceptionRaised(Assertion):

    """TODO"""

    def __init__(
        self, raised_exception, expected_exceptions,
        pattern=None, func=None, description=None, category=None,
    ):
        expected_exceptions = make_tuple(expected_exceptions)
        assert expected_exceptions, '`expected_exceptions` cannot be empty.'
        assert [issubclass(exc, Exception) for exc in expected_exceptions], (
            'items in `expected_exceptions` must be subclass of `Exception` .'
            )
        if func:
            assert callable(func), '`func` must be a callable.'
        if pattern:
            assert isinstance(pattern, six.string_types), (
                '`pattern` must be of string type, it was: {}'.format(
                    type(pattern))
            )

        self.raised_exception = raised_exception
        self.expected_exceptions = expected_exceptions
        self.pattern = pattern
        self.func = func

        # These will be set by `evaluate`
        self.exception_match = None
        self.pattern_match = None
        self.func_match = None

        super(ExceptionRaised, self).__init__(
            description=description, category=category)

    def get_match_context(self):
        exception_match = isinstance(
            self.raised_exception, self.expected_exceptions)
        pattern_match = self.pattern is None or re.search(
            self.pattern, str(self.raised_exception))
        func_match = self.func is None or self.func(self.raised_exception)
        return exception_match, pattern_match, func_match

    def evaluate(self):
        match_ctx = self.get_match_context()
        self.exception_match, self.pattern_match, self.func_match = match_ctx
        return all(match_ctx)


class ExceptionNotRaised(ExceptionRaised):

    def evaluate(self):
        return not super(ExceptionNotRaised, self).evaluate()


_SliceComparison = collections.namedtuple(
    '_SliceComparison',
    'slice comparison_indices mismatch_indices actual expected')


class SliceComparison(_SliceComparison):
    """
    Simple data container that will be generated
    as a result of EqualSlice / EqualExcludeSlices assertions

    Attributes:

        slice: Slice object
        comparison_indices: List of integers, may correspond to the indices
                            that sit inside or outside the given slice,
                            depending on the assertion type.
        mismatch_indices: List of integers that correspond to
                          items that fail equality check.
        actual: Original iterable, may be made up of items that sit inside or
                outside the slice range depending on assertion type.
        expected: Expected iterable, may be made up of items that sit inside or
                outside the slice range depending on assertion type.
    """

    @property
    def passed(self):
        return not self.mismatch_indices


class EqualSlices(Assertion):
    """
    Assertion that checks if the given slices of two iterables match.
    Generates a list of SliceComparison objects as data.
    """

    def __init__(
        self, actual, expected,
        slices, description=None, category=None,
    ):
        assert slices and isinstance(slices, (list, tuple))
        self.actual = actual
        self.expected = expected
        self.slices = slices

        self.data = []  # will be populated via self.evaluate
        self.included_indices = set()
        super(EqualSlices, self).__init__(
            description=description, category=category)

    def get_comparison_indices(self, slice_obj, iterable):
        """
        Generate a list of indices to be used
        for comparison for the given slice and iterable.
        """
        return range(*slice_obj.indices(len(iterable)))

    def get_iterable(self, iterable, comparison_indices):
        """
        Generate the iterable that is being used
        for the current slice comparison
        """
        items = [
            i for idx, i in enumerate(iterable)
            if idx in comparison_indices]

        if isinstance(iterable, six.string_types):
            return ''.join(items)
        return type(iterable)(items)

    def generate_data(self, slices, actual, expected):
        """Build a list of ``SliceComparison`` objects, for each slice."""
        result = []

        for slice_ in slices:
            indices = self.get_comparison_indices(slice_, expected)
            mismatch_indices = [
                idx for idx in indices
                if actual[idx] != expected[idx]]

            result.append(
                SliceComparison(
                    slice=slice_,
                    comparison_indices=sorted(indices),
                    mismatch_indices=sorted(mismatch_indices),
                    actual=self.get_iterable(actual, indices),
                    expected=self.get_iterable(expected, indices)
                )
            )
        return result

    def evaluate(self):
        """Equal slices assertion passes if all slice comparisons pass."""
        actual, expected = self.actual, self.expected

        if len(actual) != len(expected):
            return False

        self.data = self.generate_data(self.slices, actual, expected)
        return all(comp.passed for comp in self.data)


class EqualExcludeSlices(EqualSlices):
    """
    Assertion that checks if the items that are outside
    slices of two iterables match.

    Generates a list of SliceComparison objects as data.
    """

    def get_comparison_indices(self, slice_obj, iterable):
        indices = super(
            EqualExcludeSlices, self).get_comparison_indices(
            slice_obj, iterable)
        return set(range(len(iterable))) - set(indices)

    def evaluate(self):
        """
        Slice exclusion evaluation generates SliceComparison data and
        explicitly checks if items in the merged exclusion indices match or not.
        """
        actual, expected = self.actual, self.expected

        if len(actual) != len(expected):
            return False

        self.data = self.generate_data(self.slices, actual, expected)

        # Slice exclusion check is a little bit more tricky,
        # as a slice comparison in this assertion's context means comparing
        # all items that sit outside the slice range, meaning we can have
        # failing SliceComparisons, but the overall assertion can still pass
        # if all items at merged comparison indices match.

        # Example:
        # slices = [slice(0, 2), slice(5, 7)]
        # actual = [0, 1, 2, 3, 4, 5, 6]
        # expected = ['a', 'b', 2, 3, 4, 'c', 'd']

        # This would produce 2 SliceComparisons that fail:
        # slice(0, 2) ==> [5, 6] != ['c', 'd']
        # slice(5, 7) ==> [0, 1] != ['a', 'b']

        # However the merged comparison indices of these
        # two slices are [2, 3, 4], which correspond to the same iterable:
        # [2, 3, 4] == [2, 3, 4], so the overall assertion passes.

        ranges = [
            range(*slice_.indices(len(self.expected))) #could just use method
            for slice_ in self.slices
        ]
        excluded_indices = {idx for range_ in ranges for idx in range_}
        self.included_indices = set(range(len(expected))) - excluded_indices

        return all(
            [actual[idx] == expected[idx]
             for idx in self.included_indices]
        )


ColumnContainComparison = collections.namedtuple(
    'ColumnContainComparison', 'idx value passed')


class ColumnContain(Assertion):
    """
    Checks if the any of the ``value`` in ``values``
    exists in the ``column`` of ``table``.
    """
    def __init__(
        self, table, values, column,
        limit=0, report_fails_only=False,
        description=None, category=None,
    ):
        self.table = get_table(table)
        self.values = values
        self.column = column
        self.limit = limit
        self.report_fails_only = report_fails_only

        self.data = []  # will be set by evaluate
        super(ColumnContain, self).__init__(
            description=description, category=category)

    def evaluate(self):
        passed = True

        for idx, row in enumerate(self.table):

            comp_obj = ColumnContainComparison(
                idx=idx,
                value=row[self.column],
                passed=row[self.column] in self.values
            )

            if not comp_obj.passed:
                passed = False

            if not self.report_fails_only or (
                        self.report_fails_only and not comp_obj.passed):
                self.data.append(comp_obj)

            if self.limit and len(self.data) >= self.limit:
                break
        return passed


_RowComparison = collections.namedtuple('_RowComparison',
                                        'idx data diff errors extra')


class RowComparison(_RowComparison):
    """
      Named tuple that stores the data and comparison results of two tables.

      The column values from the first table is stored in the `data` attribute.

      If there are diffs, errors or custom comparators on the second
      table's row, diff / errors / extra dicts will be populated accordingly.

      We can then use this information to render two tables completely.

      idx: Index of the row on the table
      data (list): Column values of the original table.
      diff (dict): Diff context of the second table's row
                  (key: column name, value: second table value
                    OR comparator representation)
      errors (dict): Errors raised during the comparison.
                  (key: column name, value: error stack trace text)
      extra (dict): Comparator representations of the second table's row,
                if there is any. This field will be populated if we use a
                custom comparator that returns True OR the other column has
                different value but is included only as a display column.
    """

    @property
    def passed(self):
        """Row comparison passes if there are no diffs or errors."""
        return not (self.diff or self.errors)

    def get_comparison_value(self, column, column_idx):
        """
        Return the comparison value (e.g. other
        side of the match) and match status.
        """
        if column in self.diff:
            return self.diff[column], False
        elif column in self.errors:
            return self.errors[column], False
        elif column in self.extra:
            return self.extra[column], True
        return self.data[column_idx], True


def get_comparison_columns(table_1, table_2, include_columns, exclude_columns):
    """
      Given two tables and inclusion / exclusion rules, return a
      list of columns that will be used for comparison.

      Inclusion/exclusion rules apply to both tables, the resulting sub-tables
      must have matching columns.

      :param table_1: First table
      :type table_1: ``list`` of ``dict``
      :param table_2: Second table
      :type table_2: ``list`` of ``dict``
      :param include_columns: Inclusion rules for columns.
      :type include_columns: ``list`` of ``str``
      :param exclude_columns: Exclusion rules for columns.
      :type exclude_columns: ``list`` of ``str``
    """

    def check_missing_columns(columns, lookup):
        """Check if ``columns`` have any missing elements from ``lookup``."""
        diff = set(lookup) - set(columns)
        if diff:
            raise ValueError('Missing columns: {}'.format(', '.join(diff)))

    if include_columns and exclude_columns:
        raise ValueError(
            'Either use `include_columns` or `exclude_columns`, not'
            ' both. (include_columns: {}, exclude_columns: {})'.format(
                include_columns, exclude_columns))

    columns_1 = table_1[0].keys() if table_1 else []
    columns_2 = table_2[0].keys() if table_2 else []

    comparison_columns = columns_1

    if include_columns:

        check_missing_columns(columns_1, lookup=include_columns)
        check_missing_columns(columns_2, lookup=include_columns)
        comparison_columns = [c for c in columns_1 if c in include_columns]

    elif exclude_columns:

        columns_1 = [c for c in columns_1 if c not in exclude_columns]
        columns_2 = [c for c in columns_2 if c not in exclude_columns]

        if set(columns_1) != set(columns_2):
            raise ValueError(
                'Table columns ("{}", "{}") do not match after'
                ' applying exclusion rules: "{}"'.format(
                    ', '.join(sorted(columns_1)),
                    ', '.join(sorted(columns_2)),
                    ', '.join(exclude_columns)
                )
            )

        comparison_columns = columns_1

    elif set(columns_1) != set(columns_2):
        raise ValueError(
            'Table columns ("{}", "{}") do not match,'
            ' consider using `include_columns` or'
            ' `exclude_columns` arguments.'.format(
                ', '.join(sorted(columns_1)),
                ', '.join(sorted(columns_2)),
            )
        )

    return comparison_columns


def compare_rows(
    table, expected_table, comparison_columns,
    display_columns, strict=True, fail_limit=0
):
    """
      Apply row by row comparison of two tables,
      creating a ``RowComparison`` for each row couple.

      :param table: Original table.
      :type table: ``list`` of ``dict``
      :param expected_table: Comparison table, it can contain
                            custom comparators as column values.
      :type expected_table: ``list`` of ``dict``
      :param comparison_columns: Columns to be used for comparison.
      :type comparison_columns: ``list`` of ``str``
      :param display_columns: Columns to be used
                            for populating ``RowComparison`` data.
      :type display_columns: ``list`` of ``str``
      :param strict: Custom comparator strictness flag, currently will
                     auto-convert non-str values to
                      ``str`` for pattern if ``False``.
      :type strict: ``bool``
      :param fail_limit: Max number of failures before aborting
                        the comparison run. Useful for large
                        tables, when we want to stop after we have N rows
                        that fail the comparison. The result will contain
                         only failing comparisons if this argument is nonzero.
      :type fail_limit: ``int``
      :returns: overall passed status and RowComparison data.
    """

    # We always want to display a superset of comparison columns
    # otherwise we can have a failing comparison but the
    # resulting data will not include the mismatch context.
    if not set(comparison_columns).issubset(display_columns):
        raise ValueError(
            'comparison_columns ({}) must be '
            'subset of display_columns ({})'.format(
                ', '.join(sorted(comparison_columns)),
                ', '.join(sorted(display_columns))))

    data = []
    num_failures = 0
    display_only = [
        col for col in display_columns if col not in comparison_columns]

    for idx, (row_1, row_2) in enumerate(zip(table, expected_table)):
        diff, errors, extra = {}, {}, {}

        for column_name in comparison_columns:
            first, second = row_1[column_name], row_2[column_name]

            passed, error = comparison.basic_compare(
                first=first, second=second, strict=strict)

            if error:
                errors[column_name] = error

            elif not passed:
                diff[column_name] = second

            # Populate extra if values differ (we don't check for equality
            # as that may have raised an error for incompatible types as well
            if first is not second and (error or passed):
                extra[column_name] = second

        row_data = [row_1[col] for col in display_columns]

        # Need to populate extra with values from the
        # second table, if they are not being used
        # for comparison but have different values.
        extra.update({
            col: row_2[col]
            for col in display_only
            if col in row_2 and row_2[col] != row_1[col]})

        row_comparison = RowComparison(idx, row_data, diff, errors, extra)

        if not row_comparison.passed:
            num_failures += 1

        # Include only failing comparisons if there is a limit
        if fail_limit > 0:

            if not row_comparison.passed:
                data.append(row_comparison)

            if num_failures >= fail_limit:
                break

        else:
            data.append(row_comparison)

    return num_failures == 0, data


class TableMatch(Assertion):
    """
      Match two tables using ``compare_rows``, may generate
      custom message if tables cannot be compared for certain reasons.
    """

    def __init__(
        self, table, expected_table,
        include_columns=None, exclude_columns=None,
        report_all=True, fail_limit=0, strict=False,
        description=None, category=None
    ):
        self.table = get_table(table)
        self.expected_table = get_table(expected_table)
        self.include_columns = include_columns
        self.exclude_columns = exclude_columns
        self.strict = strict
        self.report_all = report_all

        self.fail_limit = fail_limit

        # these will populated by self.evaluate
        self.display_columns = None
        self.message = None
        self.data = []

        super(TableMatch, self).__init__(
            description=description, category=category)

    def evaluate(self):
        len_table, len_expected = len(self.table), len(self.expected_table)

        if len_table != len_expected:
            self.message = (
                'Cannot run comparison on tables with different number '
                'of rows ({} vs {}), make sure tables have the same size.'
            ).format(len_table, len_expected)
            return False

        if not (self.table or self.expected_table):
            self.message = 'Both tables are empty.'
            return True

        try:
            comparison_columns = get_comparison_columns(
                table_1=self.table,
                table_2=self.expected_table,
                include_columns=self.include_columns,
                exclude_columns=self.exclude_columns
            )
        except ValueError as exc:
            self.message = str(exc)
            return False  # Fail on invalid tables

        self.display_columns = self.table[0].keys()\
            if self.report_all else comparison_columns

        passed, self.data = compare_rows(
            table=self.table,
            expected_table=self.expected_table,
            comparison_columns=comparison_columns,
            display_columns=self.display_columns,
            strict=self.strict,
            fail_limit=self.fail_limit,
        )
        return passed


_XMLTagComparison = collections.namedtuple(
    '_XMLTagComparison', 'tag diff error extra')


class XMLTagComparison(_XMLTagComparison):
    """
      Named tuple that stores the data and comparison results XML tags.
    """

    @property
    def passed(self):
        """Tag comparison passes if there are no diff or error."""
        return not (self.diff or self.error)

    @property
    def comparison_value(self):
        result = self.error or self.diff or self.extra or self.tag
        if comparison.is_regex(result):
            result = "REGEX('{}')".format(result.pattern)
        return result


class XMLCheck(Assertion):
    """
    Validate XML tag texts or existence in a given xpath,
    supports regex patterns as tag values as well.
    """

    def __init__(
        self, element, xpath, tags=None,
        namespaces=None, description=None, category=None
    ):

        self.xpath = xpath
        self.tags = tags

        if isinstance(element, six.string_types):
            element = lxml.etree.fromstring(element)

        # pylint: disable=protected-access
        elif not isinstance(element, lxml.etree._Element):
            raise ValueError(
                '`element` must be either an XML'
                ' string or `lxml.etree.Element`.'
                ' It was of type: {}'.format(type(element)))

        self.element = element
        self.namespaces = namespaces
        self.data = []  # will be populated by evaluate
        self.message = None  # will be populated by evaluate
        super(XMLCheck, self).__init__(
            description=description, category=category)

    def evaluate(self):
        element, namespaces = self.element, self.namespaces
        xpath, tags = self.xpath, self.tags

        # This may raise XPathEvalError for incorrect namespacing
        results = element.xpath(xpath, namespaces=namespaces)

        # xpath does not exist in XML
        if not results:
            self.message = 'xpath: `{}` does not' \
                           ' exist in the XML.'.format(xpath)
            return False

        # xpath exists, no tag lookup -> Pass
        if not tags:
            self.message = 'xpath: `{}` exists in the XML.'.format(xpath)
            return True

        data = []

        # Tag lookup in xpath
        for idx, tag in enumerate(tags):
            try:
                text = results[idx].text

                if not text:
                    xml_comp = XMLTagComparison(
                        tag=tag,
                        diff=None,
                        error='No value is found,'
                              ' although the path exists.',
                        extra=None,
                    )
                elif isinstance(tag, str) and re.match(tag, text):
                    extra = tag if tag != text else None
                    xml_comp = XMLTagComparison(
                        tag=text, diff=None, error=None, extra=extra)
                else:
                    passed, error = comparison.basic_compare(
                        first=text, second=tag)

                    if error:
                        xml_comp = XMLTagComparison(
                            tag=text, diff=None, error=error, extra=tag)

                    elif not passed:
                        xml_comp = XMLTagComparison(
                            tag=text, diff=tag, error=None, extra=None)

                    else:
                        xml_comp = XMLTagComparison(
                            tag=text, diff=None, error=None, extra=tag)

            except IndexError:
                xml_comp = XMLTagComparison(
                    tag=None,
                    diff=tag,
                    error='No tags found for the index: {}'.format(idx),
                    extra=None
                )
            data.append(xml_comp)

        self.data = data
        return all([comp.passed for comp in self.data])


class DictCheck(Assertion):
    """
        Assertion that checks if a given ``dict`` contains
        (or does not contain) given keys.
    """

    def __init__(
        self, dictionary, has_keys=None,
        absent_keys=None, description=None, category=None,
    ):
        self.dictionary = dictionary
        self.has_keys = has_keys
        self.absent_keys = absent_keys

        self.has_keys_diff = None  # will be set by evaluate
        self.absent_keys_diff = None  # will be set by evaluate

        super(DictCheck, self).__init__(
            description=description, category=category)

    def evaluate(self):
        result = comparison.check_dict_keys(
            data=self.dictionary,
            has_keys=self.has_keys,
            absent_keys=self.absent_keys
        )
        self.has_keys_diff, self.absent_keys_diff = result
        return not (self.has_keys_diff or self.absent_keys_diff)


class FixCheck(DictCheck):

    def __init__(
        self, msg, has_tags=None, absent_tags=None,
        description=None, category=None,
    ):
        super(FixCheck, self).__init__(
            dictionary=msg,
            has_keys=has_tags,
            absent_keys=absent_tags,
            description=description,
            category=category
        )


class DictMatch(Assertion):

    def __init__(
        self, value, expected,
        include_keys=None, exclude_keys=None, report_all=True,
        description=None, category=None,
        actual_description=None, expected_description=None
    ):
        self.value = value
        self.expected = expected
        self.include_keys = include_keys
        self.exclude_keys = exclude_keys
        self.actual_description = actual_description
        self.report_all = report_all
        self.expected_description = expected_description

        self.comparison = None  # will be set by evaluate
        super(DictMatch, self).__init__(
            description=description, category=category)

    def evaluate(self):
        passed, cmp_result = comparison.compare(
            lhs=self.value,
            rhs=self.expected,
            ignore=self.exclude_keys,
            only=self.include_keys,
            report_all=self.report_all
        )
        self.comparison = flatten_dict_comparison(cmp_result)
        return passed


class FixMatch(DictMatch):
    """
        Similar to DictMatch, however dict keys
        will have fix tag info popups on web UI
    """
    def __init__(
        self, value, expected,
        include_tags=None, exclude_tags=None, report_all=True,
        description=None, category=None,
        actual_description=None, expected_description=None
    ):

        super(FixMatch, self).__init__(
            value=value, expected=expected,
            include_keys=include_tags,
            exclude_keys=exclude_tags,
            report_all=report_all,
            description=description,
            category=category,
            actual_description=actual_description,
            expected_description=expected_description
        )


class DictMatchAll(Assertion):

    def __init__(
        self, values, comparisons,
        key_weightings=None, description=None, category=None,
    ):
        self.comparisons = comparisons
        self.values = values
        self.key_weightings = key_weightings

        self.matches = None
        self.result = None  # will be set by evaluate
        super(DictMatchAll, self).__init__(
            description=description, category=category)

    def evaluate(self):
        self.matches, self.result = comparison.dictmatch_all_compat(
            match_name=self.__class__.__name__,
            comparisons=self.comparisons,
            values=self.values,
            key_weightings=self.key_weightings,
            description=self.description,
        )

        for match in self.matches:
            match['comparison'] = flatten_dict_comparison(match['comparison'])

        return self.result.passed


class FixMatchAll(DictMatchAll):
    """
        Similar to DictMatchAll, however dict keys
        will have fix tag info popups on web UI
    """
    def __init__(
        self, values, comparisons,
        tag_weightings=None, description=None, category=None,
    ):
        super(FixMatchAll, self).__init__(
            values=values,
            comparisons=comparisons,
            key_weightings=tag_weightings,
            description=description,
            category=category,
        )