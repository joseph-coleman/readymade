"""A DataTable's rows in an SQLite database: load_sql(), save_sql(), changes, conflicts, and
changes to the columns that keep every row."""

import datetime
import sqlite3
import time
from decimal import Decimal as D

import pytest

from readymade import Form, data, formfile
from readymade.controls import REGISTRY
from readymade.data import ConflictError, DataError

SHOP = """
CREATE TABLE items (id INTEGER PRIMARY KEY, name VARCHAR(30) NOT NULL UNIQUE, price DECIMAL(10,2) DEFAULT 1.5,
                    qty INTEGER, added DATE, ok BOOLEAN, picture BLOB);
INSERT INTO items (name, price, qty, added, ok) VALUES ('Rake', 12.5, 3, '2026-10-01', 1), ('Hoe', 9.99, 0, NULL, 0),
                                                       ('Spade', 20, 5, '2026-09-30', 1);
CREATE TABLE notes (body TEXT, stars INTEGER);
INSERT INTO notes VALUES ('fine', 4), ('meh', 2);
CREATE INDEX items_qty ON items (qty);
CREATE TRIGGER items_named AFTER UPDATE OF name ON items BEGIN UPDATE items SET qty = qty WHERE id = new.id; END;
"""


@pytest.fixture
def shop(tmp_path):
    path = tmp_path / "shop.db"
    connection = sqlite3.connect(path)
    connection.executescript(SHOP)
    connection.commit()
    connection.close()
    return path


@pytest.fixture
def make_table(tmp_path):
    made = []

    def make(columns=("Item",)):
        design = formfile.FormDesign(name="Form1", width=480, height=260)
        spec = REGISTRY["DataTable"].new_spec("Stock", 8, 8, 460, 240)
        spec["columns"] = list(columns)
        design.controls.append(spec)
        formfile.save(design, tmp_path / "Form1.form")
        form = Form(tmp_path / "Form1.form")
        form.show()
        form.root.update()
        made.append(form)
        return form.Stock

    yield make
    for form in made:
        if form.Stock.database is not None:
            form.Stock.database.close()
        form.root.destroy()


def other(path):
    """Another program's connection to the database."""
    return sqlite3.connect(path, isolation_level=None)


def rows_of(path, sql="SELECT name, price, qty FROM items ORDER BY id"):
    with sqlite3.connect(path) as connection:
        return connection.execute(sql).fetchall()


# ----- types and values (no window) -----

def test_declared_types_and_kinds():
    assert data.kind_of("INTEGER") == {"kind": "number", "decimals": 0}
    assert data.kind_of("varchar( 30 )") == {"kind": "text", "max_length": 30}
    assert data.kind_of("DECIMAL(10,4)") == {"kind": "money", "decimals": 4}
    assert data.kind_of("decimal") == {"kind": "money", "decimals": 2}
    assert [data.kind_of(t)["kind"] for t in ("REAL", "DOUBLE PRECISION", "NUMERIC", "", "NVARCHAR", "CLOB")] == [
        "number", "number", "number", "text", "text", "text"]
    assert [data.kind_of(t)["kind"] for t in ("DATE", "time", "DATETIME", "TIMESTAMP", "BOOLEAN")] == [
        "date", "time", "datetime", "datetime", "check"]
    assert data.kind_of("BLOB") is None
    assert data.guess([1, 2, None]) == {"kind": "number", "decimals": 0} and data.guess([1, 2.5])["kind"] == "number"
    assert data.guess(["2026-10-01", None])["kind"] == "date" and data.guess(["09:30"])["kind"] == "time"
    assert data.guess(["2026-10-01 09:30"])["kind"] == "datetime" and data.guess(["x", "2026-10-01"])["kind"] == "text"


def test_the_sql_of_a_column_definition_is_changed_in_place():
    tokens = data._tokens('"Unit price" DECIMAL(10, 2) CONSTRAINT c NOT NULL DEFAULT 0 REFERENCES p (id) '
                          'ON DELETE SET NULL CHECK (qty >= 0)')
    changed = data._altered_definition(tokens, {"type": "TEXT", "notnull": False, "default": "'x'"})
    assert changed.strip() == '"Unit price" TEXT REFERENCES p (id) ON DELETE SET NULL CHECK (qty >= 0) DEFAULT \'x\''
    assert data._altered_definition(data._tokens("a INT"), {"unique": True, "notnull": True}).strip() == \
        "a INT NOT NULL UNIQUE"


# ----- loading -----

@pytest.mark.usefixtures("display")
def test_a_tables_columns_come_from_its_schema(make_table, shop):
    table = make_table()
    assert table.load_sql(shop, "items") == []
    assert table.names == ["id", "name", "price", "qty", "added", "ok"]  # (the BLOB left out)
    kinds = {c.name: c for c in table.columns}
    assert kinds["id"].readonly and kinds["id"].unique and not kinds["id"].required  # (numbered by the database)
    assert kinds["name"].required and kinds["name"].unique and kinds["name"].max_length == 30
    assert kinds["price"].kind == "money" and kinds["price"].default == D("1.50")
    assert kinds["qty"].kind == "number" and kinds["added"].kind == "date" and kinds["ok"].kind == "check"
    assert table.rows[0] == [1, "Rake", D("12.50"), 3, datetime.date(2026, 10, 1), True]
    assert table[1, "added"] is None and table[1, "ok"] is False and table[2, "price"] == D("20.00")
    assert not table.changed and table.database is not None

    table.load_sql(shop, "notes")  # (no key: SQLite's rowid, hidden, last)
    assert table.names == ["body", "stars", "rowid"] and table.columns["rowid"].hidden
    assert table.headers[:2] == ["body", "stars"] and table.rows[1] == ["meh", 2, 2]


@pytest.mark.usefixtures("display")
def test_a_query_and_its_table(make_table, shop):
    table = make_table()
    table.load_sql(shop, "SELECT id, name, qty * 2 AS twice FROM items WHERE qty > ? ORDER BY name", (1,),
                   table="items")
    assert table["name"] == ["Rake", "Spade"] and table.columns["twice"].readonly  # (not the table's: shown)
    table[0, "name"] = "Big rake"
    table[0, "twice"] = 100  # (code can; it isn't saved)
    table.save_sql()
    assert rows_of(shop)[0] == ("Big rake", 12.5, 3)

    with pytest.raises(ValueError, match="need its key"):
        table.load_sql(shop, "SELECT name FROM items", table="items")
    table.load_sql(shop, "SELECT name, qty FROM items")  # (no table to save to: shown, not saved)
    table[0, "name"] = "x"
    with pytest.raises(ValueError, match="no table to save them to"):
        table.save_sql()
    with pytest.raises(FileNotFoundError):
        table.load_sql("nowhere.db", "items")


@pytest.mark.usefixtures("display")
def test_keep_the_programs_own_columns(make_table, shop):
    table = make_table(["Name", "Qty : number", "Picked : check", {"name": "Price", "kind": "money", "min": 0}])
    table.load_sql(shop, "items", columns="keep")
    assert table.names == ["Name", "Qty", "Picked", "Price", "id"] and table.columns["id"].hidden  # (its key, added)
    assert table.rows[0] == ["Rake", 3, None, D("12.50"), 1]
    table[0, "Picked"] = True  # (the program's own: not saved)
    table[0, "Qty"] = 4
    table.save_sql()
    assert rows_of(shop)[0] == ("Rake", 12.5, 4)
    assert not table.changed


@pytest.mark.usefixtures("display")
def test_values_that_arent_their_columns_kind_are_loaded_as_text(make_table, shop):
    with other(shop) as connection:
        connection.execute("UPDATE items SET qty = 'lots', added = 1760000000 WHERE name = 'Hoe'")
    table = make_table()
    found = table.load_sql(shop, "items")
    assert [(m.row, m.column, m.value, m.declared) for m in found] == [(1, "qty", "lots", "INTEGER"),
                                                                       (1, "added", 1760000000, "DATE")]
    assert table.columns["qty"].kind == "text" and table["qty"] == ["3", "lots", "5"]
    assert table[1, "added"] == "1760000000" and table.columns["price"].kind == "money"
    table[0, "name"] = "Rake 2"
    table.save_sql()  # (the column's text here: its type there is left alone)
    assert rows_of(shop, "SELECT type FROM pragma_table_info('items') WHERE name = 'qty'") == [("INTEGER",)]
    assert rows_of(shop)[0] == ("Rake 2", 12.5, 3)


# ----- saving rows -----

@pytest.mark.usefixtures("display")
def test_changes_are_saved_and_read_back(make_table, shop):
    table = make_table()
    table.load_sql(shop, "items")
    table[0, "price"] = "13.25"
    table.rows.append({"name": "Trowel", "qty": 7})
    del table.rows[1]
    changes = table.changes()
    assert changes.added == [2] and changes.edited == [0] and changes.columns == []
    assert [row["name"] for row in changes.deleted] == ["Hoe"] and table.changed
    assert table[2, "id"] is None and table[2, "price"] == D("1.50")  # (its default; numbered when saved)
    table.save_sql()
    assert table[2, "id"] == 4 and not table.changed
    assert rows_of(shop) == [("Rake", 13.25, 3), ("Spade", 20, 5), ("Trowel", 1.5, 7)]
    table[2, "qty"] = 8  # (a row saved is a row loaded: saved again as an edit)
    table.save_sql()
    assert rows_of(shop)[-1] == ("Trowel", 1.5, 8)
    table.rows[0] = [None, "Rake", "1.00", 1]  # (the same row, its values changed)
    table.save_sql()
    assert rows_of(shop)[0] == ("Rake", 1.0, 1) and table[0, "id"] == 1


@pytest.mark.usefixtures("display")
def test_the_rules_are_checked_before_anything_is_saved(make_table, shop):
    table = make_table()
    table.load_sql(shop, "items")
    with table.unchecked():
        table[0, "name"] = None
        table[1, "qty"] = 50
    with pytest.raises(DataError) as raised:
        table.save_sql()
    assert [(p.row, p.rule) for p in raised.value.problems] == [(0, "required")]
    assert rows_of(shop)[1] == ("Hoe", 9.99, 0)  # (nothing saved)
    table[0, "name"] = "Rake"
    table.save_sql()
    assert rows_of(shop)[1] == ("Hoe", 9.99, 50)


@pytest.mark.usefixtures("display")
def test_a_database_error_rolls_everything_back(make_table, shop):
    with other(shop) as connection:  # (a rule the table doesn't know of)
        connection.execute("CREATE TRIGGER few BEFORE UPDATE OF qty ON items WHEN new.qty > 10 BEGIN "
                           "SELECT RAISE(ABORT, 'too many'); END")
    table = make_table()
    table.load_sql(shop, "items")
    table[0, "price"] = 1
    table[1, "qty"] = 50
    with pytest.raises(sqlite3.IntegrityError, match="row 1: too many"):
        table.save_sql()
    assert rows_of(shop)[0] == ("Rake", 12.5, 3) and table.changed


@pytest.mark.usefixtures("display")
def test_rows_changed_by_someone_else_are_a_conflict(make_table, shop):
    table = make_table()
    table.load_sql(shop, "items")
    with other(shop) as connection:
        connection.execute("UPDATE items SET qty = 30 WHERE name = 'Rake'")
        connection.execute("DELETE FROM items WHERE name = 'Hoe'")
        connection.execute("UPDATE items SET qty = 50 WHERE name = 'Spade'")  # (a row not changed here: fine)
    table[0, "price"] = 1
    table[1, "qty"] = 1
    table.rows.append({"name": "Fork"})
    with pytest.raises(ConflictError) as raised:
        table.save_sql()
    assert isinstance(raised.value, DataError)
    rows = raised.value.rows
    assert rows[0][0] == 0 and rows[0][1]["qty"] == 30 and rows[0][1]["price"] == D("12.50")
    assert rows[1] == (1, None)  # (gone)
    assert "row 0 was changed in the database" in str(raised.value)
    assert rows_of(shop) == [("Rake", 12.5, 30), ("Spade", 20, 50)]  # (nothing saved: not the new row either)
    table.save_sql(overwrite=True)
    assert rows_of(shop) == [("Rake", 1, 30), ("Spade", 20, 50), ("Fork", 1.5, None)]  # (its changes: the price)


@pytest.mark.usefixtures("display")
def test_a_save_waits_for_another_programs(make_table, shop, monkeypatch):
    monkeypatch.setattr(data, "BUSY_SECONDS", 0.2)
    table = make_table()
    table.load_sql(shop, "items")
    table[0, "qty"] = 9
    with other(shop) as connection:
        connection.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            table.save_sql()
        assert time.monotonic() - started >= 0.15
        connection.execute("ROLLBACK")
    table.save_sql()
    assert rows_of(shop)[0] == ("Rake", 12.5, 9)


@pytest.mark.usefixtures("display")
def test_revert(make_table, shop):
    table = make_table()
    table.load_sql(shop, "items")
    table[0, "qty"] = 99
    del table.rows[2]
    table.rows.append({"name": "Fork"})
    table.columns.append("Notes")
    table.revert()
    assert table.names == ["id", "name", "price", "qty", "added", "ok"] and len(table.rows) == 3
    assert table[0, "qty"] == 3 and table[2, "name"] == "Spade" and not table.changed


# ----- saving the columns' changes: every row kept -----

@pytest.mark.usefixtures("display")
def test_new_renamed_and_deleted_columns(make_table, shop):
    table = make_table()
    table.load_sql(shop, "items")
    table.columns.append({"name": "notes", "max_length": 50})
    table.columns.append({"name": "aisle", "kind": "number", "decimals": 0, "default": 1})
    table.columns.append({"name": "total", "kind": "money", "formula": lambda row: row["price"] * 2})
    table.columns["qty"].name = "stock"
    del table.columns["added"]
    table[0, "notes"] = "by the door"
    assert table.changes().columns == [("drop", "added"), ("rename", "qty", "stock"), ("add", "notes"),
                                       ("add", "aisle")]  # (total: worked out, not saved)
    table.save_sql()
    with sqlite3.connect(shop) as connection:
        columns = [row[1:3] for row in connection.execute("PRAGMA table_info(items)")]
        assert columns == [("id", "INTEGER"), ("name", "VARCHAR(30)"), ("price", "DECIMAL(10,2)"),
                           ("stock", "INTEGER"), ("ok", "BOOLEAN"), ("picture", "BLOB"), ("notes", "VARCHAR(50)"),
                           ("aisle", "INTEGER")]
        assert connection.execute("SELECT name, stock, notes, aisle FROM items").fetchall() == [
            ("Rake", 3, "by the door", 1), ("Hoe", 0, None, 1), ("Spade", 5, None, 1)]
    assert not table.changed and table.changes().columns == []
    table[1, "stock"] = 4  # (saved under its new name)
    table.save_sql()
    assert rows_of(shop, "SELECT stock FROM items") == [(3,), (4,), (5,)]


@pytest.mark.usefixtures("display")
def test_a_kind_or_rule_changed_rebuilds_the_table_keeping_it_all(make_table, shop):
    with other(shop) as connection:
        connection.execute("UPDATE items SET picture = x'89504e47' WHERE name = 'Rake'")
        connection.executescript("CREATE TABLE orders (id INTEGER PRIMARY KEY, item INTEGER REFERENCES items (id)); "
                                 "INSERT INTO orders (item) VALUES (1); CREATE VIEW cheap AS SELECT name FROM items "
                                 "WHERE price < 10;")
    table = make_table()
    table.load_sql(shop, "items")
    table.columns["qty"].kind = "money"  # (to the cent: money's places, not INTEGER's none)
    table.columns["qty"].required = True
    table.columns["price"].default = 2
    table.columns["name"].unique = False
    table.save_sql()
    with sqlite3.connect(shop) as connection:
        info = {row[1]: row[2:5] for row in connection.execute("PRAGMA table_info(items)")}
        assert info["qty"] == ("DECIMAL(18,2)", 1, None) and info["price"] == ("DECIMAL(10,2)", 0, "2.00")
        assert info["name"] == ("VARCHAR(30)", 1, None)
        assert connection.execute("SELECT name, qty, hex(picture) FROM items").fetchall() == [
            ("Rake", 3, "89504E47"), ("Hoe", 0, ""), ("Spade", 5, "")]  # (every row, and what wasn't loaded)
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        assert {"items_qty", "items_named", "cheap", "orders"} <= names  # (its index, trigger; the view)
        assert connection.execute("SELECT * FROM cheap").fetchall() == [("Hoe",)]
        assert not [row for row in connection.execute("PRAGMA index_list(items)") if row[2] and row[3] == "u"]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert table["qty"] == [D("3.00"), D("0.00"), D("5.00")] and not table.changed
    table.rows.append({"name": "Rake", "qty": 1})  # (no longer unique)
    table.save_sql()
    assert len(rows_of(shop)) == 4


@pytest.mark.usefixtures("display")
def test_the_key_stays_as_it_is(make_table, shop):
    table = make_table()
    table.load_sql(shop, "items")
    del table.columns["id"]
    with pytest.raises(ValueError, match="key"):
        table.save_sql()
    table.revert()
    table.columns["name"].key = True
    with pytest.raises(ValueError, match="key"):
        table.save_sql()


# ----- a new table -----

@pytest.mark.usefixtures("display")
def test_saving_to_a_new_table(make_table, tmp_path):
    table = make_table([{"name": "Code", "key": True}, {"name": "Price", "kind": "money", "min": 0}, "Due : date"])
    table.columns.append({"name": "Twice", "kind": "money", "formula": lambda row: row["Price"] * 2})
    table.rows = [["A1", "2.50", "2026-10-17"], ["B2", None, None]]
    table.save_sql("new.db", "prices")
    assert rows_of(tmp_path / "new.db", "SELECT * FROM prices") == [("A1", 2.5, "2026-10-17"), ("B2", None, None)]
    assert data.read_schema(table.database, "prices").keys == ["Code"]
    table[1, "Price"] = 4  # (it's the new table's now)
    table.save_sql("new.db", "prices")  # (as save_sql(): it's where the rows are from)
    assert rows_of(tmp_path / "new.db", "SELECT Price FROM prices") == [(2.5,), (4,)]
    table[0, "Price"] = 3
    table.save_sql("new.db", "prices", replace=True)  # (made again, every row written)
    assert rows_of(tmp_path / "new.db", "SELECT Price FROM prices") == [(3,), (4,)]

    plain = make_table(["Name", "Qty : number"])  # (no key: rowid, hidden)
    plain.rows = [["a", 1], ["b", 2]]
    with pytest.raises(ValueError, match="has a table prices already"):
        plain.save_sql(tmp_path / "new.db", "Prices")
    plain.save_sql(tmp_path / "plain.db", "things")
    assert plain.names == ["Name", "Qty", "rowid"] and plain["rowid"] == [1, 2]
    plain[0, "Qty"] = 5
    plain.save_sql()
    assert rows_of(tmp_path / "plain.db", "SELECT * FROM things") == [("a", 5), ("b", 2)]


@pytest.mark.usefixtures("display")
def test_a_connection_of_the_programs_own(make_table, shop):
    connection = sqlite3.connect(shop)
    table = make_table()
    table.load_sql(connection, "notes")
    assert table.database is connection
    table[0, "stars"] = 5
    table.save_sql()
    assert rows_of(shop, "SELECT stars FROM notes") == [(5,), (2,)]
    connection.execute("UPDATE notes SET stars = 1")  # (not committed: a save waits for that)
    with pytest.raises(ValueError, match="commit"):
        table.save_sql()
    connection.rollback()
    connection.close()


@pytest.mark.usefixtures("display")
def test_two_columns_swap_names(make_table, shop):
    table = make_table()
    table.load_sql(shop, "notes")
    table.columns["body"].name = "was body"
    table.columns["stars"].name = "body"
    table.columns["was body"].name = "stars"
    assert table.changes().columns == [("rename", "body", "stars"), ("rename", "stars", "body")]
    table.save_sql()
    assert rows_of(shop, "SELECT stars, body FROM notes") == [("fine", 4), ("meh", 2)]


@pytest.mark.usefixtures("display")
def test_a_key_of_text_edited(make_table, tmp_path):
    path = tmp_path / "codes.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("CREATE TABLE codes (code TEXT PRIMARY KEY, what TEXT) WITHOUT ROWID; "
                                 "INSERT INTO codes VALUES ('A', 'apple'), ('B', 'banana');")
    table = make_table()
    table.load_sql(path, "codes")
    assert table.names == ["code", "what"] and table.columns["code"].key  # (no rowid to add)
    table[0, "code"] = "AP"  # (found by the key it was loaded with)
    table.rows.append(["C", "cherry"])
    table.save_sql()
    assert rows_of(path, "SELECT * FROM codes ORDER BY code") == [("AP", "apple"), ("B", "banana"), ("C", "cherry")]
    table[0, "what"] = "apricot"  # (and by its new one, after)
    table.save_sql()
    assert rows_of(path, "SELECT what FROM codes WHERE code = 'AP'") == [("apricot",)]
    with table.unchecked():
        table[1, "code"] = "C"  # (two the same: the rules say so first)
    with pytest.raises(DataError, match="unique|is in row"):
        table.save_sql()
