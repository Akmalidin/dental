import {registerRoot, delayRender, continueRender} from 'remotion';
import {waitForFonts} from './fonts';
import {RemotionRoot} from './Root';

const handle = delayRender('Loading brand fonts (Manrope / Inter / JetBrains Mono)');
waitForFonts()
  .then(() => continueRender(handle))
  .catch((err) => {
    console.error('Font loading failed', err);
    continueRender(handle);
  });

registerRoot(RemotionRoot);
