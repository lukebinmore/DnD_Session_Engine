from DnDSessionEngine.core.theme import con
from rich.table import Table


def build_table(values, headers=[], title=None, numbered=False):
    if title:
        table = Table(
            title=title,
            title_style="table.title",
            border_style="table.border",
            show_header=True,
            header_style="table.header",
            show_lines=True,
        )
    else:
        table = Table(
            border_style="table.border",
            show_header=True,
            header_style="table.header",
            show_lines=True,
        )

    table.add_column(headers[0], style="table.column1", no_wrap=True)
    table.add_column(headers[1], style="table.column2", overflow="fold")

    if numbered:
        for idx, value in enumerate(values):
            table.add_row(str(idx), value[0])
    else:
        for key, value in values.items():
            table.add_row(key, str(value) if str(value).strip() else "[empty]<EMPTY>[/]")

    con.print(table)
