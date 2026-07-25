import pytest
from gtk_llm_chat.pango_markdown import extract_tables, has_table, split_table_blocks


class TestMarkdownTables:

    def test_simple_table_detected(self):
        text = "| a | b |\n| - | - |\n| 1 | 2 |"
        assert has_table(text)

    def test_no_table_plain_text(self):
        assert not has_table("Hello world")

    def test_no_table_paragraph(self):
        assert not has_table("Some **bold** text with `code`")


class TestExtractTables:

    def test_simple_two_col(self):
        text = (
            "| Name | Value |\n"
            "| ---- | ----- |\n"
            "| foo  | 42    |\n"
        )
        tables = extract_tables(text)
        assert len(tables) == 1
        t = tables[0]
        assert t['headers'] == ['Name', 'Value']
        assert t['rows'] == [['foo', '42']]

    def test_no_header(self):
        text = (
            "| 1 | 2 |\n"
            "| - | - |\n"
            "| 3 | 4 |\n"
        )
        tables = extract_tables(text)
        assert len(tables) == 1
        assert tables[0]['headers'] == ['1', '2']
        assert tables[0]['rows'] == [['3', '4']]

    def test_mixed_prose_and_table(self):
        text = (
            "Hello\n\n"
            "| x | y |\n"
            "| - | - |\n"
            "| a | b |\n"
            "\nWorld"
        )
        assert has_table(text)

    def test_escaped_pipe(self):
        text = (
            "| Col |\n"
            "| - |\n"
            "| a \\| b |\n"
        )
        tables = extract_tables(text)
        assert len(tables) == 1

    def test_malformed_table_no_rows(self):
        text = (
            "| H |\n"
            "| - |\n"
        )
        tables = extract_tables(text)
        assert len(tables) == 1
        assert tables[0]['rows'] == []

    def test_wide_table(self):
        cols = ['C' + str(i) for i in range(10)]
        header = '| ' + ' | '.join(cols) + ' |'
        sep = '| ' + ' | '.join('-' for _ in cols) + ' |'
        row = '| ' + ' | '.join('x' for _ in cols) + ' |'
        text = f"{header}\n{sep}\n{row}"
        tables = extract_tables(text)
        assert len(tables) == 1
        assert len(tables[0]['headers']) == 10

    def test_multiple_tables(self):
        text = (
            "| A |\n"
            "| - |\n"
            "| 1 |\n"
            "\n"
            "| B |\n"
            "| - |\n"
            "| 2 |\n"
        )
        tables = extract_tables(text)
        assert len(tables) == 2

    def test_prose_around_table_is_preserved(self):
        text = (
            "Before\n\n"
            "| A | B |\n"
            "| - | - |\n"
            "| 1 | 2 |\n"
            "After without a blank separator"
        )
        blocks = split_table_blocks(text)
        assert [kind for kind, _value in blocks] == ['text', 'table', 'text']
        assert blocks[0][1] == 'Before'
        assert blocks[2][1] == 'After without a blank separator'
