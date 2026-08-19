import {loadFont as loadManrope} from '@remotion/google-fonts/Manrope';
import {loadFont as loadInter} from '@remotion/google-fonts/Inter';
import {loadFont as loadMono} from '@remotion/google-fonts/JetBrainsMono';

const manrope = loadManrope('normal', {
  weights: ['700', '800'],
  subsets: ['cyrillic', 'latin'],
});
const inter = loadInter('normal', {
  weights: ['400', '500', '600'],
  subsets: ['cyrillic', 'latin'],
});
const mono = loadMono('normal', {
  weights: ['400', '500', '600'],
  subsets: ['latin'],
});

export const fonts = {
  display: manrope.fontFamily,
  body: inter.fontFamily,
  mono: mono.fontFamily,
};

export const waitForFonts = (): Promise<unknown> =>
  Promise.all([manrope.waitUntilDone(), inter.waitUntilDone(), mono.waitUntilDone()]);
