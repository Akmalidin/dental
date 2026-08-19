import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setChromiumOpenGlRenderer("angle");
Config.setBrowserExecutable(
  "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell"
);
Config.setChromiumDisableWebSecurity(true);
Config.setChromiumHeadlessMode(true);
Config.setDelayRenderTimeoutInMilliseconds(120000);
Config.setConcurrency(1);
