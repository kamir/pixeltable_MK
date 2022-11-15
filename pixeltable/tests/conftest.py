from pathlib import Path

import pytest
import sqlalchemy as sql

import pixeltable as pt
import pixeltable.catalog as catalog
from pixeltable.type_system import ColumnType
from pixeltable.tests.utils import read_data_file

def init_env(tmp_path) -> None:
    engine = sql.create_engine('sqlite:///:memory:', echo=True)
    from pixeltable import env
    env.init_env(tmp_path, engine)

@pytest.fixture(scope='function')
def test_db(tmp_path) -> None:
    init_env(tmp_path)

@pytest.fixture(scope='session')
def test_img_tbl(tmp_path_factory) -> catalog.Table:
    init_env(tmp_path_factory.mktemp('base'))
    cl = pt.Client()
    db = cl.create_db('test')
    cols = [
        catalog.Column('img', ColumnType.IMAGE, nullable=False),
        catalog.Column('category', ColumnType.STRING, nullable=False),
        catalog.Column('split', ColumnType.STRING, nullable=False),
    ]
    tbl = db.create_table('test', cols)
    df = read_data_file('imagenette2-160', 'manifest.csv', ['img'])
    tbl.insert_pandas(df[:20])
    return tbl
