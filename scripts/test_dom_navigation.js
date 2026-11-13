
const jsdom = require("jsdom");
const { JSDOM } = jsdom;
const dom = new JSDOM(`<!DOCTYPE html><html><body><label data-orig-text="Agentenprofile">Profile</label></body></html>`);
const el = dom.window.document.querySelector("label");
console.log(el.dataset.origText);

