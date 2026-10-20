import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from autoposts import core, media


@pytest.fixture
def media_db(tmp_path, monkeypatch):
    monkeypatch.setattr(core.settings, 'data_dir', tmp_path)
    core.init_db()
    core.execute('INSERT INTO users(id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)',
                 ('owner', 'media@example.com', 'Pessoa', 'unused', core.now()))
    return tmp_path


def post(**updates):
    result = {
        'id': 'render-test', 'user_id': 'owner', 'title': 'Uma ideia que merece movimento',
        'caption': 'Teste real de renderização', 'duration': 6, 'theme': 'violet',
        'scenes': [{'text': 'Seu conteúdo começa com uma boa ideia.'},
                   {'text': 'Transforme inspiração em ação. Publique com propósito.'}],
    }
    result.update(updates)
    return result


@pytest.mark.parametrize('theme', ['violet', 'ocean', 'ember'])
def test_scene_frames_are_vertical_and_readable(theme):
    frame = media._scene_frame(post(theme=theme), {'text': 'Olá, criação!\nConteúdo em português.'}, 0, 2, None)
    assert frame.size == (1080, 1920)
    assert frame.mode == 'RGB'
    assert frame.getpixel((90, 120)) != frame.getpixel((500, 1800))
    frame.close()


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg is required')
def test_real_mp4_has_instagram_compatible_video_audio_and_duration(media_db):
    image_path = media_db / 'uploads' / 'sample.jpg'
    Image.new('RGB', (700, 500), (74, 110, 170)).save(image_path)
    core.execute('INSERT INTO assets(id,user_id,filename,original_name,media_type,kind,size,created_at) VALUES(?,?,?,?,?,?,?,?)',
                 ('photo', 'owner', 'sample.jpg', 'sample.jpg', 'image/jpeg', 'image', image_path.stat().st_size, core.now()))
    rendered = post(scenes=[{'text': 'Olá, mundo! Criação com imagens próprias.', 'asset_id': 'photo'},
                            {'text': '', 'asset_id': 'photo'}])
    filename = media.render_post(rendered)
    path = media_db / 'videos' / filename
    assert filename == 'render-test.mp4'
    assert path.is_file() and path.stat().st_size > 10_000
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                           check=True, capture_output=True, text=True)
    data = json.loads(probe.stdout)
    video = next(stream for stream in data['streams'] if stream['codec_type'] == 'video')
    audio = next(stream for stream in data['streams'] if stream['codec_type'] == 'audio')
    assert (video['codec_name'], video['width'], video['height'], video['pix_fmt']) == ('h264', 1080, 1920, 'yuv420p')
    assert audio['codec_name'] == 'aac'
    assert abs(float(data['format']['duration']) - 6) < 0.15
    assert list((media_db / 'tmp').iterdir()) == []


def test_unowned_asset_is_rejected_without_rendering(media_db):
    core.execute('INSERT INTO users(id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)',
                 ('other', 'other@example.com', 'Outro', 'unused', core.now()))
    core.execute('INSERT INTO assets(id,user_id,filename,original_name,media_type,kind,size,created_at) VALUES(?,?,?,?,?,?,?,?)',
                 ('private', 'other', 'private.jpg', 'private.jpg', 'image/jpeg', 'image', 1, core.now()))
    with pytest.raises(media.RenderError, match='não está mais disponível'):
        media.render_post(post(scenes=[{'text': 'Test', 'asset_id': 'private'}]))
    assert list((media_db / 'videos').iterdir()) == []


def test_asset_symlink_cannot_escape_upload_directory(media_db, tmp_path):
    outside = tmp_path / 'outside.jpg'
    Image.new('RGB', (10, 10)).save(outside)
    (media_db / 'uploads' / 'link.jpg').symlink_to(outside)
    core.execute('INSERT INTO assets(id,user_id,filename,original_name,media_type,kind,size,created_at) VALUES(?,?,?,?,?,?,?,?)',
                 ('link', 'owner', 'link.jpg', 'link.jpg', 'image/jpeg', 'image', 1, core.now()))
    with pytest.raises(media.RenderError):
        media._owned_image(post(), 'link')


@pytest.mark.parametrize('updates', [
    {'id': '../escape'}, {'duration': 0}, {'duration': True}, {'duration': 61},
    {'scenes': []}, {'scenes': [{'text': ''}]}, {'scenes': 'invalid JSON'}, {'theme': 'unknown'},
])
def test_invalid_render_inputs_are_rejected(media_db, updates):
    with pytest.raises(media.RenderError):
        media.render_post(post(**updates))


def test_missing_ffmpeg_has_actionable_error(media_db, monkeypatch):
    monkeypatch.setattr(media.shutil, 'which', lambda _: None)
    with pytest.raises(media.RenderError, match='FFmpeg'):
        media.render_post(post())


def test_long_word_wraps_inside_safe_area():
    font = media._font(70, bold=True)
    lines = media._wrap('a' * 90, font, 300)
    assert len(lines) > 1
    assert all(font.getlength(line) <= 300 for line in lines)
