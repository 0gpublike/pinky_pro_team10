"""다른 PC 설치 경로 및 미션 다운로드/재로드 호환성."""
from pathlib import Path

import pytest
import yaml

from pinky_fleet_station.mission_io import Mission, MissionError, load_mission, save_mission, resolve_map_path


def data(path):
    return {'map': {'yaml_path': path}, 'robots': [
        {'name': 'pinky1', 'domain_id': 10}, {'name': 'pinky2', 'domain_id': 11}]}


def test_package_mission_moves_between_installations(monkeypatch, tmp_path):
    import ament_index_python.packages as packages
    share = tmp_path / 'alice_ws/install/pinky_fleet_sim/share/pinky_fleet_sim'
    monkeypatch.setattr(packages, 'get_package_share_directory', lambda _: str(share))
    uri = 'package://pinky_fleet_sim/map/fleet_arena.yaml'
    mission = Mission(data(uri))
    assert mission.map_yaml_path == str(share / 'map/fleet_arena.yaml')
    destination = tmp_path / 'download.yaml'
    save_mission(mission, destination)
    assert yaml.safe_load(destination.read_text())['map']['yaml_path'] == uri
    share = tmp_path / 'bob_ws/install/pinky_fleet_sim/share/pinky_fleet_sim'
    assert load_mission(destination).map_yaml_path == str(share / 'map/fleet_arena.yaml')
    mission.map_yaml_path = '/custom/map.yaml'
    assert mission.to_dict()['map']['yaml_path'] == '/custom/map.yaml'


def test_symlink_resolution_keeps_portable_reference(monkeypatch, tmp_path):
    import ament_index_python.packages as packages
    source = tmp_path / 'source'
    source.mkdir()
    install = tmp_path / 'install'
    install.symlink_to(source, target_is_directory=True)
    monkeypatch.setattr(packages, 'get_package_share_directory', lambda _: str(install))
    uri = 'package://test/map.yaml'
    mission = Mission(data(uri))
    mission.map_yaml_path = str(Path(mission.map_yaml_path).resolve())
    assert mission.to_dict()['map']['yaml_path'] == uri


@pytest.mark.parametrize('uri', ['package://', 'package://test', 'package://test/../map.yaml', 'package://test//map.yaml'])
def test_invalid_package_path(uri):
    with pytest.raises(MissionError):
        resolve_map_path(uri)


def test_missing_package_explains_setup(monkeypatch):
    import ament_index_python.packages as packages
    def missing(_):
        raise LookupError('missing')
    monkeypatch.setattr(packages, 'get_package_share_directory', missing)
    with pytest.raises(MissionError, match='source'):
        resolve_map_path('package://missing/map.yaml')


def test_existing_home_and_absolute_paths(monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path))
    assert resolve_map_path('~/maps/map.yaml') == str(tmp_path / 'maps/map.yaml')
    assert resolve_map_path('$HOME/maps/map.yaml') == str(tmp_path / 'maps/map.yaml')
    assert resolve_map_path('/tmp/map.yaml') == '/tmp/map.yaml'


def test_packaged_default_maps_open():
    from pinky_fleet_station.web_node import WebNode
    root = Path(__file__).resolve().parents[1]
    for filename in ('mission_web.yaml', 'mission_real_web.yaml'):
        mission = load_mission(root / 'config' / filename)
        info, png, _ = WebNode.read_map(None, mission.to_dict()['map']['yaml_path'])
        assert info['width'] > 0 and png.startswith(b'\x89PNG')
