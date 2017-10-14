#!/usr/bin/env python3
import os
import random
import inspect
import threading

import hug
import fire
from pyorderby import orderby
from cached_property import cached_property

from .log import get_logger
from .client import SpotifyClient
from .server import StandaloneApplication
from .volume import AlsaVolumeControl, LinuxVolumeControl, SpotifyVolumeControl, ApplescriptVolumeControl
from .constants import TimeRange, AudioFeature, VolumeBackend

logger = get_logger()


class Spotify(SpotifyClient):
    """Spotify high-level wrapper."""

    def __init__(self, device=None, alsa_device=None, alsa_mixer=None, audio_device=None, **kwargs):
        super().__init__(**kwargs)
        self.device_name = device or os.getenv('SPOTIFY_DEVICE')
        self.alsa_device = alsa_device or os.getenv('SPOTIFY_ALSA_DEVICE')
        self.alsa_mixer = alsa_mixer or os.getenv('SPOTIFY_ALSA_MIXER')
        self.audio_device = audio_device or os.getenv('SPOTIFY_AUDIO_DEVICE')

    def __dir__(self):
        names = super().__dir__()
        return [name for name in names if not name.startswith('_')]

    @cached_property
    def _device(self):
        return self.get_device(device=self.device_name)

    @cached_property
    def _applescript_volume_control(self):
        if os.uname().sysname != 'Darwin':
            return

        return ApplescriptVolumeControl(self.audio_device)

    @cached_property
    def _linux_volume_control(self):
        if os.uname().sysname != 'Linux':
            return

        return LinuxVolumeControl(self, self.alsa_mixer, spotify_device=self._device, alsa_device=self.alsa_device)

    @cached_property
    def _alsa_volume_control(self):
        if os.uname().sysname != 'Linux':
            return

        return AlsaVolumeControl(self.alsa_mixer, device=self.alsa_device)

    @cached_property
    def _spotify_volume_control(self):
        return SpotifyVolumeControl(self, device=self._device)

    def change_volume(self, value=0, backend=VolumeBackend.SPOTIFY.value):
        assert backend in VolumeBackend or backend in [b.value for b in VolumeBackend]

        volume = None
        if backend in (VolumeBackend.ALSA, VolumeBackend.ALSA.value):
            volume = self._alsa_volume_control.volume + value
            self._alsa_volume_control.volume = volume
        elif backend in (VolumeBackend.APPLESCRIPT, VolumeBackend.APPLESCRIPT.value):
            volume = self._applescript_volume_control.volume + value
            self._applescript_volume_control.volume = volume
        elif backend in (VolumeBackend.SPOTIFY, VolumeBackend.SPOTIFY.value):
            volume = self._spotify_volume_control.volume + value
            self._spotify_volume_control.volume = volume

        return volume

    def volume_up(self, backend=VolumeBackend.SPOTIFY.value):
        return self.change_volume(value=+1, backend=backend)

    def volume_down(self, backend=VolumeBackend.SPOTIFY.value):
        return self.change_volume(value=-1, backend=backend)

    def play(self, tracks, device_id=None, fade=False, volume=80, fade_args={}):
        if fade:
            if self._applescript_volume_control:
                target = self._applescript_volume_control.fade
                if self.audio_device:
                    self._applescript_volume_control.switch_audio_device(self.audio_device)
            elif self._linux_volume_control:
                target = self._linux_volume_control.fade
                self._spotify_volume_control.volume = volume
            elif self._alsa_volume_control:
                target = self._alsa_volume_control.fade
                self._spotify_volume_control.volume = volume
            else:
                target = self._spotify_volume_control.fade

            threading.Thread(target=target, kwargs=fade_args).start()

        return self.start_playback(tracks=tracks, device_id=self._device.id or device_id)

    def server(self, **options):
        for name, method in inspect.getmembers(self, inspect.ismethod):
            hug.get(f'/{name}')(method)

        from .client import __hug__ as client_hug
        __hug__.extend(client_hug)  # noqa

        app = StandaloneApplication(__hug_wsgi__, **options)  # noqa
        app.run()


def main():
    """Main function."""

    try:
        fire.Fire(Spotify)
    except KeyboardInterrupt:
        print('Quitting')


if __name__ == '__main__':
    main()
