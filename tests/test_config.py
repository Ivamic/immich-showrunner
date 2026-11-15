# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path, PurePosixPath

import pytest
from pydantic import ValidationError

from showrunner.config import Settings, parse_path_map


def settings(**values: str) -> Settings:
    base = {"immich_url": "http://immich.test:2283", "immich_api_key": "key"}
    return Settings(_env_file=None, **{**base, **values})  # type: ignore[arg-type, unused-ignore]


def test_defaults() -> None:
    s = settings()
    assert (s.show_prefix, s.person_prefix) == ("§ ", "• ")
    assert s.title_max_length == 80
    assert s.path_mappings == ()


def test_url_is_normalized() -> None:
    assert settings(immich_url=" http://immich.test:2283/ ").immich_url == "http://immich.test:2283"


def test_url_without_scheme_is_rejected() -> None:
    with pytest.raises(ValidationError):
        settings(immich_url="immich.test:2283")


def test_api_key_is_not_printed() -> None:
    assert "key" not in repr(settings().immich_api_key)


def test_path_map_longest_source_first() -> None:
    mappings = parse_path_map("/data=/srv/immich ; /data/external=/mnt/ext;")
    assert [str(m.source) for m in mappings] == ["/data/external", "/data"]
    assert mappings[0].target == PurePosixPath("/mnt/ext")


@pytest.mark.parametrize("value", ["/data", "data=/srv", "/data=srv", "/data=/srv/../etc"])
def test_bad_path_map_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        parse_path_map(value)
    with pytest.raises(ValidationError):
        settings(path_map=value)


def test_jellyfin_output_folder_under_its_old_name() -> None:
    assert settings().jellyfin_dir is None
    assert str(settings(output_dir="/output").jellyfin_dir) == str(Path("/output"))
    both = settings(output_dir="/old", jellyfin_output_dir="/new")
    assert str(both.jellyfin_dir) == str(Path("/new"))
    # compose.yaml passes an empty value for a folder that is not set.
    assert settings(jellyfin_output_dir="", output_dir=" ").jellyfin_dir is None


def test_a_sync_needs_an_output_folder() -> None:
    from showrunner.runner import SetupError, outputs_from

    with pytest.raises(SetupError, match="SHOWRUNNER_JELLYFIN_OUTPUT_DIR"):
        outputs_from(settings(path_map="/data=/mnt/immich"), dry_run=True)
    outputs = outputs_from(settings(path_map="/data=/mnt/immich", output_dir="/x"), dry_run=True)
    assert [(o.target.name, o.executor, o.notify) for o in outputs] == [("jellyfin", None, False)]
