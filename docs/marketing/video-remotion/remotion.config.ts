import {Config} from '@remotion/cli/config';

Config.setBrowserExecutable(
  '/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell',
);
Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
// The sandboxed environment routes HTTPS through a proxy with its own CA,
// which Chromium doesn't trust by default — only affects Google Fonts fetches
// during rendering, not the output video content.
Config.setChromiumIgnoreCertificateErrors(true);
