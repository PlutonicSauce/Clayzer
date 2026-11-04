// JSX-like templates for Preact without a build step: html`<${Component} prop=${x} />`.
import { h } from "preact";
import htm from "htm";

export const html = htm.bind(h);
