'use strict';
const clock = document.querySelector('#clock');
function updateClock() { clock.textContent = new Date().toLocaleTimeString('ru-RU'); }
updateClock(); setInterval(updateClock, 1000);
document.querySelector('#year').textContent = new Date().getFullYear();
document.querySelector('#color').addEventListener('click', () => document.body.classList.toggle('alt'));
