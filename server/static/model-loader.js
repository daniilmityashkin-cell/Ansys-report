// Import Three.js and create a context only when this particular panel is opened.
import {whenVisible} from './model-runtime.js';
for (const panel of document.querySelectorAll('[data-model-module]')) {
  whenVisible(panel, async () => {
    panel.dataset.modelState = 'loading';
    await import(panel.dataset.modelModule);
    panel.dataset.modelState = 'loaded';
  });
}
// Collapsed fallback images do not compete with the interactive overview.
for (const image of document.querySelectorAll('img[data-preview-src]')) {
  whenVisible(image, async () => { image.src = image.dataset.previewSrc; delete image.dataset.previewSrc; });
}
