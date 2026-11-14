import numpy as np
import pytest
import requests

from app.errors import APIError, UpstreamError
from app.services import usda
from tests.conftest import FAKE_DS


@pytest.mark.parametrize("code,group,subtype", [
    (1, "corn", None), (12, "corn", "Sweet corn"), (13, "corn", "Popcorn or ornamental corn"),
    (22, "wheat", "Durum wheat"), (23, "wheat", "Spring wheat"), (24, "wheat", "Winter wheat"),
])
def test_corn_and_wheat_class_mapping(code, group, subtype):
    d = usda.describe_code(code)
    assert d["group"] == group and d["crop"] == group and d["subtype"] == subtype


@pytest.mark.parametrize("code", [26, 225, 226, 228, 236, 237, 238, 241])
def test_double_crop_classes_are_not_simple_corn_or_wheat(code):
    d = usda.describe_code(code)
    assert d["group"] == "double_crop" and d["crop"] is None
    assert code not in usda.CORN_CODES + usda.WHEAT_CODES


def test_no_data_and_other(monkeypatch):
    monkeypatch.setattr(usda, "class_name", lambda c: "Soybeans")
    assert usda.describe_code(None)["group"] == "no_data"
    assert usda.describe_code(5) == {"code": 5, "official_name": "Soybeans", "group": "other", "crop": None, "subtype": None}


def test_tile_validation():
    with pytest.raises(APIError):
        usda.validate_tile(3, 0, 0, usda.TILE_MIN_Z, usda.TILE_MAX_Z)
    with pytest.raises(APIError):
        usda.validate_tile(5, 32, 0, usda.TILE_MIN_Z, usda.TILE_MAX_Z)
    usda.validate_tile(5, 7, 11, usda.TILE_MIN_Z, usda.TILE_MAX_Z)


def test_tile_outside_conus_makes_no_upstream_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not call USDA")

    monkeypatch.setattr(usda, "export_window", boom)
    png = usda.tile_png("corn", 6, 0, 0, FAKE_DS, None)  # far from CONUS
    assert png == usda.empty_png()


def test_export_window_bounds_size():
    with pytest.raises(APIError):
        usda.export_window((0, 0, 1, 1), 5000, 5000, FAKE_DS)
    with pytest.raises(APIError):
        usda.export_window((1, 1, 0, 0), 10, 10, FAKE_DS)


def test_outlines_only_on_fixed_grid():
    with pytest.raises(APIError):
        usda.outline_tile(10, 0, 0, FAKE_DS, None)


def test_identify_upstream_failure(monkeypatch):
    def fail(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(usda._http, "get", fail)
    with pytest.raises(UpstreamError) as ei:
        usda.identify(-93.5, 42.0, FAKE_DS)
    assert ei.value.code == "usda_unavailable"


def test_dataset_discovery_picks_newest_year_and_falls_back(monkeypatch):
    class Resp:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    feats = [{"attributes": {"OBJECTID": 39, "Name": "2024_10m_cdls", "Year": 2024}},
             {"attributes": {"OBJECTID": 41, "Name": "2026_10m_cdls", "Year": 2026}},
             {"attributes": {"OBJECTID": 99, "Name": "something_else", "Year": 2030}}]
    monkeypatch.setattr(usda._http, "get", lambda *a, **k: Resp({"features": feats}))
    usda.reset_dataset_cache()
    ds = usda.get_dataset()
    assert (ds.year, ds.raster_id, ds.status) == (2026, 41, "live")

    def fail(*a, **k):
        raise requests.Timeout("slow")

    monkeypatch.setattr(usda._http, "get", fail)
    usda.reset_dataset_cache()
    ds = usda.get_dataset()
    assert ds.status == "last_verified_record"
    assert ds.year == usda.MANIFEST["last_verified"]["year"]
    assert "last verified record" in ds.status_note
    usda.reset_dataset_cache()


def test_render_tile_only_colours_requested_crop():
    from io import BytesIO

    from PIL import Image

    arr = np.array([[1, 24], [225, 0]], dtype=np.uint8)
    img = np.array(Image.open(BytesIO(usda.render_tile_png(arr, "corn"))))
    assert img[0, 0, 3] == 255      # corn painted
    assert img[0, 1, 3] == 0        # wheat not in corn layer
    assert img[1, 0, 3] == 0        # double crop WinWht/Corn never painted as corn
