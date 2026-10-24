"""Functional tests of what the page uses."""

from __future__ import annotations

import httpx

from conftest import create, sample, upload_all, wait_status


def test_page_shows_the_three_steps_and_variants(client: httpx.Client) -> None:
    page = client.get("/").text
    for text in ["Upload in parts", "Forget receipts and resume (ListParts)", "S3 event (default)",
                 "Crash the worker on its next task", "Watch with adaptive bitrate", "Slow edge",
                 "Origin shield", "/vendor/hls.min.js"]:
        assert text in page, text
    assert client.get("/vendor/hls.min.js").status_code == 200


def test_sample_clip_is_a_video(client: httpx.Client) -> None:
    r = client.get("/v1/lab/sample.mp4", params={"seconds": 8})
    assert r.headers["content-type"] == "video/mp4" and r.content[4:8] == b"ftyp"


def test_watch_metadata_shape_and_cache_layers(client: httpx.Client) -> None:
    data = sample(client)
    video = create(client, data)
    processing = client.get(f"/v1/videos/{video['videoId']}").json()
    assert processing["status"] == "uploading" and processing["servedFrom"] == "postgres"
    client.post(f"/v1/videos/{video['videoId']}/complete", json={"parts": upload_all(client, video, data)})
    ready = wait_status(client, video["videoId"], {"ready"})
    assert set(ready) >= {"videoId", "title", "status", "durationSec", "manifestUrl", "deliveries", "renditions"}
    assert set(ready["deliveries"]) == {"cdn", "slow", "noShield", "origin"}
    again = client.get(f"/v1/videos/{video['videoId']}").json()
    assert again["servedFrom"] in {"in-process cache", "redis"}, "a ready video is served from a cache"


def test_slow_edge_is_rate_limited(client: httpx.Client) -> None:
    ready = next(v for v in client.get("/v1/videos").json()["videos"] if v["status"] == "ready")
    view = client.get(f"/v1/videos/{ready['video_id']}").json()
    seg = view["deliveries"]["slow"].replace("master.m3u8", "720p/seg_00000.ts")
    r = httpx.get(seg, timeout=60)
    assert r.status_code == 200
    assert r.elapsed.total_seconds() > 1.0, "about 100 KB/s, so a 720p segment takes seconds"
