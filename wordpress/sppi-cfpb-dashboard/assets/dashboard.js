/**
 * SPPI CFPB complaint dashboard renderer.
 *
 * Dependency-free by design: charts and the choropleth are hand-built SVG. A
 * charting or mapping library would be a third-party script on a public page,
 * another thing to keep patched, and a problem on hosts with a strict CSP.
 *
 * Data arrives inline as window.SPPI_CFPB (set server-side by the plugin). If
 * absent, the script fetches the feed itself, so the same file also drives a
 * plain HTML page.
 *
 * Colour, type and ground are inherited from the host theme; see dashboard.css.
 */
(function () {
	'use strict';

	var NS = 'http://www.w3.org/2000/svg';
	var DEFAULT_FEED = 'data/dashboard.json';
	var DEFAULT_MAP = 'assets/us-states.json';

	var SUPPORTS_MIX = (function () {
		try {
			return CSS.supports('color', 'color-mix(in srgb, red 50%, transparent)');
		} catch (e) { return false; }
	})();

	var STATE_NAMES = {
		AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California',
		CO: 'Colorado', CT: 'Connecticut', DE: 'Delaware', DC: 'District of Columbia',
		FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois',
		IN: 'Indiana', IA: 'Iowa', KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana',
		ME: 'Maine', MD: 'Maryland', MA: 'Massachusetts', MI: 'Michigan',
		MN: 'Minnesota', MS: 'Mississippi', MO: 'Missouri', MT: 'Montana',
		NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire', NJ: 'New Jersey',
		NM: 'New Mexico', NY: 'New York', NC: 'North Carolina', ND: 'North Dakota',
		OH: 'Ohio', OK: 'Oklahoma', OR: 'Oregon', PA: 'Pennsylvania',
		RI: 'Rhode Island', SC: 'South Carolina', SD: 'South Dakota',
		TN: 'Tennessee', TX: 'Texas', UT: 'Utah', VT: 'Vermont', VA: 'Virginia',
		WA: 'Washington', WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming'
	};

	// States too small to carry an inline label at this scale; they remain
	// hoverable and keyboard-reachable, they just are not lettered.
	var NO_LABEL = { DC: 1, RI: 1, DE: 1, CT: 1, NJ: 1, MA: 1, NH: 1, VT: 1, MD: 1 };

	/* ------------------------------------------------------------------ */
	/* helpers                                                             */
	/* ------------------------------------------------------------------ */

	function el(tag, attrs, text) {
		var n = document.createElement(tag);
		for (var k in attrs || {}) n.setAttribute(k, attrs[k]);
		if (text !== undefined && text !== null) n.textContent = String(text);
		return n;
	}

	function svgEl(tag, attrs, text) {
		var n = document.createElementNS(NS, tag);
		for (var k in attrs || {}) n.setAttribute(k, attrs[k]);
		if (text !== undefined && text !== null) n.textContent = String(text);
		return n;
	}

	function fmt(n) {
		if (n === null || n === undefined) return '—';
		return Number(n).toLocaleString('en-US');
	}

	function pct(n, dp) {
		if (n === null || n === undefined) return '—';
		return Number(n).toFixed(dp === undefined ? 1 : dp) + '%';
	}

	function monthLabel(m) {
		var names = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
			'August', 'September', 'October', 'November', 'December'];
		var p = String(m).split('-');
		return p.length === 2 ? names[parseInt(p[1], 10) - 1] + ' ' + p[0] : m;
	}

	/** Series colour at a given strength, adapting to the host background. */
	function seriesFill(varName, strength, fallbackRgb) {
		if (SUPPORTS_MIX) {
			return 'color-mix(in srgb, var(' + varName + ') ' + strength + '%, transparent)';
		}
		return 'rgba(' + fallbackRgb + ',' + (strength / 100).toFixed(2) + ')';
	}

	/* ------------------------------------------------------------------ */
	/* chart scaffolding                                                   */
	/* ------------------------------------------------------------------ */

	/**
	 * Chart geometry, in viewBox units.
	 *
	 * Roughly 3:1. The dashboard sits in the theme's wide measure, so a chart is
	 * typically rendered around 1200px across; at the previous 2.4:1 that came
	 * out 500px tall and pushed the panel below it off the screen.
	 */
	var W = 960, H = 340, PAD = { l: 70, r: 22, t: 18, b: 44 };

	/** Rendered size we want chart text to end up at, in real CSS pixels. */
	var TICK_PX = 12.5;

	/**
	 * Keep chart text at a constant apparent size.
	 *
	 * Text inside an SVG is measured in viewBox units, so it scales with the
	 * element: a 11-unit label was 8.9px when the chart sat in a 580px column
	 * and would be 18px in a 1200px one. Neither is what anybody chose. Setting
	 * font-size on the root <svg> makes every label inherit it in user units, so
	 * the size only has to be divided by the current scale factor to land at
	 * TICK_PX on screen at any width.
	 *
	 * The upper clamp matters on phones: without it a 360px-wide chart would ask
	 * for a 33-unit font and the y-axis labels would run into the plot area.
	 */
	function fitText(svg) {
		function apply() {
			var w = svg.getBoundingClientRect().width;
			if (!w) return;
			var units = TICK_PX * W / w;
			svg.style.fontSize = Math.min(22, Math.max(9, units)).toFixed(2) + 'px';
		}
		apply();
		if (typeof ResizeObserver === 'function') {
			new ResizeObserver(apply).observe(svg);
		} else {
			window.addEventListener('resize', apply);
		}
		// The first measurement can happen before the theme's webfonts and
		// layout have settled; one more pass after load costs nothing.
		window.addEventListener('load', apply);
	}

	function frame(title, desc) {
		var s = svgEl('svg', {
			viewBox: '0 0 ' + W + ' ' + H,
			class: 'sppi-chart',
			role: 'img',
			tabindex: '0',
			'aria-label': title
		});
		s.appendChild(svgEl('title', {}, title));
		if (desc) s.appendChild(svgEl('desc', {}, desc));
		return s;
	}

	function yScale(v, lo, hi) {
		var span = H - PAD.t - PAD.b;
		var f = hi === lo ? 0 : (v - lo) / (hi - lo);
		return H - PAD.b - span * f;
	}

	function xScale(i, n) {
		var span = W - PAD.l - PAD.r;
		return PAD.l + (n <= 1 ? 0 : span * i / (n - 1));
	}

	/**
	 * Gridline values that read as round numbers.
	 *
	 * Dividing the axis into four equal parts is arithmetically tidy and
	 * typographically bad: a 50% axis becomes 0, 12.5, 25, 37.5, 50, and
	 * "12.5%" is half again as wide as "10%". On a phone that is the difference
	 * between a label sitting in the gutter and one hanging outside the chart.
	 * Picking a round step instead keeps every label short.
	 *
	 * @param {number} hi Top of the axis.
	 * @return {number[]} Tick values from 0 to hi inclusive.
	 */
	function niceTicks(hi) {
		var steps = [1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000];
		var step = hi / 5;
		for (var i = 0; i < steps.length; i++) {
			if (hi / steps[i] <= 5) { step = steps[i]; break; }
		}
		var out = [];
		for (var v = 0; v <= hi + step / 1000; v += step) out.push(v);
		return out;
	}

	/*
	 * Labels are offset with `dy` in `em` rather than a fixed number of units,
	 * because fitText() changes the font size after these are drawn. An em
	 * offset rescales with the text; a unit offset would leave the labels
	 * stranded above or below their gridline at some widths.
	 */
	function gridY(svg, ticks, lo, hi) {
		ticks.forEach(function (t) {
			var y = yScale(t.v, lo, hi);
			svg.appendChild(svgEl('line', { x1: PAD.l, y1: y, x2: W - PAD.r, y2: y, class: 'sppi-grid' }));
			svg.appendChild(svgEl('text', {
				x: PAD.l - 10, y: y, dy: '0.32em', class: 'sppi-tick', 'text-anchor': 'end'
			}, t.label));
		});
	}

	function xLabels(svg, labels, every) {
		labels.forEach(function (lab, i) {
			if (i % every !== 0 && i !== labels.length - 1) return;
			svg.appendChild(svgEl('text', {
				x: xScale(i, labels.length), y: H - PAD.b, dy: '1.5em',
				class: 'sppi-tick', 'text-anchor': 'middle'
			}, lab));
		});
	}

	function polyline(svg, values, lo, hi, cls) {
		var runs = [], run = [];
		values.forEach(function (v, i) {
			if (v === null || v === undefined || isNaN(v)) {
				if (run.length > 1) runs.push(run);
				run = [];
				return;
			}
			run.push(xScale(i, values.length).toFixed(1) + ',' + yScale(v, lo, hi).toFixed(1));
		});
		if (run.length > 1) runs.push(run);
		runs.forEach(function (r) {
			svg.appendChild(svgEl('polyline', { points: r.join(' '), class: 'sppi-line ' + cls }));
		});
	}

	function figureWrap(svg) {
		var f = el('figure', { class: 'sppi-figure' });
		f.appendChild(svg);
		fitText(svg);
		return f;
	}

	/**
	 * Attach a crosshair, per-series markers and a tooltip to a line chart.
	 *
	 * Pointer position is mapped back through the viewBox rather than assuming
	 * pixel coordinates, so it stays correct at any rendered width. Arrow keys
	 * step the cursor for keyboard users, and the readout is mirrored into an
	 * aria-live region so it is announced rather than only drawn.
	 */
	function makeInteractive(fig, svg, cfg) {
		var n = cfg.labels.length;
		if (!n) return;

		var tip = el('div', { class: 'sppi-tip', role: 'status', 'aria-live': 'polite' });
		fig.appendChild(tip);

		var cross = svgEl('line', { class: 'sppi-crosshair', y1: PAD.t, y2: H - PAD.b, x1: -99, x2: -99 });
		svg.appendChild(cross);

		var dots = cfg.series.map(function (s) {
			var c = svgEl('circle', { class: 'sppi-dot ' + s.cls, r: 4, cx: -99, cy: -99 });
			c.style.display = 'none';
			svg.appendChild(c);
			return c;
		});

		var current = -1;

		function hide() {
			current = -1;
			tip.removeAttribute('data-show');
			cross.setAttribute('x1', -99);
			cross.setAttribute('x2', -99);
			dots.forEach(function (d) { d.style.display = 'none'; });
		}

		function show(i) {
			if (i < 0 || i >= n) return;
			current = i;
			var x = xScale(i, n);
			cross.setAttribute('x1', x);
			cross.setAttribute('x2', x);

			var rows = '';
			cfg.series.forEach(function (s, si) {
				var v = s.values[i];
				var dot = dots[si];
				if (v === null || v === undefined || isNaN(v)) {
					dot.style.display = 'none';
					return;
				}
				dot.style.display = '';
				dot.setAttribute('cx', x);
				dot.setAttribute('cy', yScale(v, cfg.lo, cfg.hi));
				rows += '<div class="sppi-tip-row"><i class="sppi-swatch ' + s.cls +
					'"></i>' + s.label + '<span class="sppi-tip-val">' +
					s.format(v, i) + '</span></div>';
			});

			tip.innerHTML = '<div class="sppi-tip-head">' + cfg.headline(i) + '</div>' + rows;
			tip.setAttribute('data-show', '1');

			// Position within the figure, flipping before it can overflow.
			var rect = svg.getBoundingClientRect();
			var px = (x / W) * rect.width;
			var tw = tip.offsetWidth;
			var left = px + 14;
			if (left + tw > rect.width - 4) left = px - tw - 14;
			if (left < 4) left = 4;
			tip.style.left = left + 'px';
			tip.style.top = Math.max(4, PAD.t / H * rect.height) + 'px';
		}

		function indexFromClientX(clientX) {
			var rect = svg.getBoundingClientRect();
			if (!rect.width) return -1;
			var vx = ((clientX - rect.left) / rect.width) * W;
			var span = W - PAD.l - PAD.r;
			var frac = (vx - PAD.l) / span;
			var i = Math.round(frac * (n - 1));
			return Math.max(0, Math.min(n - 1, i));
		}

		svg.addEventListener('pointermove', function (e) {
			show(indexFromClientX(e.clientX));
		});
		svg.addEventListener('pointerleave', hide);
		svg.addEventListener('pointerdown', function (e) {
			// Touch: tap to pin a reading rather than requiring hover.
			show(indexFromClientX(e.clientX));
		});
		svg.addEventListener('blur', hide);
		svg.addEventListener('keydown', function (e) {
			var step = e.shiftKey ? 12 : 1;
			if (e.key === 'ArrowRight') { show(Math.min(n - 1, (current < 0 ? -1 : current) + step)); }
			else if (e.key === 'ArrowLeft') { show(Math.max(0, (current < 0 ? n : current) - step)); }
			else if (e.key === 'Home') { show(0); }
			else if (e.key === 'End') { show(n - 1); }
			else if (e.key === 'Escape') { hide(); return; }
			else { return; }
			e.preventDefault();
		});
	}

	function legend(items) {
		var d = el('div', { class: 'sppi-legend' });
		items.forEach(function (it) {
			var s = el('span', { class: 'sppi-legend-item' });
			s.appendChild(el('i', { class: 'sppi-swatch ' + it.cls }));
			s.appendChild(document.createTextNode(it.label));
			d.appendChild(s);
		});
		return d;
	}

	/**
	 * Heading level for panel titles.
	 *
	 * The dashboard normally sits under the page title, so h2 is the level that
	 * continues the document outline instead of skipping one. Overridable via
	 * the shortcode when the dashboard is nested under a heading of its own.
	 */
	var HEADING = 'h2';

	function section(title, blurb) {
		var w = el('section', { class: 'sppi-panel' });
		w.appendChild(el(HEADING, { class: 'sppi-panel-title sppi-prose' }, title));
		if (blurb) w.appendChild(el('p', { class: 'sppi-panel-note sppi-prose' }, blurb));
		return w;
	}

	/* ------------------------------------------------------------------ */
	/* panels                                                              */
	/* ------------------------------------------------------------------ */

	function panelHeadline(d) {
		var h = d.headline, m = d.meta;
		var w = el('div', { class: 'sppi-stats' });
		[
			[pct(h.templated_pct, 1), 'of published complaint narratives are word-for-word copies of at least ' + (m.template_threshold - 1) + ' others'],
			[fmt(h.templated), 'complaints using a text repeated ' + m.template_threshold + '+ times'],
			[fmt(h.distinct_templates), 'distinct templates in circulation'],
			[fmt(h.complaints), 'complaints analysed, 2011 to ' + String(m.data_through).slice(0, 4)]
		].forEach(function (s) {
			var c = el('div', { class: 'sppi-stat' });
			c.appendChild(el('b', { class: 'sppi-stat-value' }, s[0]));
			c.appendChild(el('span', { class: 'sppi-stat-label' }, s[1]));
			w.appendChild(c);
		});
		return w;
	}

	function panelTrend(d) {
		if (!d.trend || !d.trend.length) return null;
		var w = section('Templated complaints over time',
			'Share of published narratives that are byte-for-byte identical to at least ' +
			(d.meta.template_threshold - 1) + ' others. Recent months are withheld until enough ' +
			'narratives are published to measure them. Hover the chart, or focus it and use the arrow keys.');
		var vals = d.trend.map(function (r) { return r.pct; });
		var labels = d.trend.map(function (r) { return r.month; });
		var hi = Math.max(10, Math.ceil(Math.max.apply(null, vals) / 10) * 10);
		var svg = frame('Templated share of narratives by month',
			'Climbs steadily from under one percent in 2016 to about ' +
			Math.round(vals[vals.length - 1]) + ' percent by ' + labels[labels.length - 1] + '.');
		var ticks = niceTicks(hi).map(function (v) {
			return { v: v, label: (Math.round(v * 10) / 10) + '%' };
		});
		gridY(svg, ticks, 0, hi);
		xLabels(svg, labels.map(function (m) { return m.slice(0, 4); }), 12);
		polyline(svg, vals, 0, hi, 'sppi-s1');

		var fig = figureWrap(svg);
		makeInteractive(fig, svg, {
			labels: labels, lo: 0, hi: hi,
			headline: function (i) { return monthLabel(labels[i]); },
			series: [{
				label: 'Templated', cls: 'sppi-s1', values: vals,
				format: function (v, i) {
					return pct(v) + ' of ' + fmt(d.trend[i].narratives);
				}
			}]
		});
		w.appendChild(fig);
		w.appendChild(legend([{ cls: 'sppi-s1', label: 'Share of narratives that are copies' }]));
		return w;
	}

	function panelVolume(d) {
		if (!d.volume || !d.volume.series || !d.volume.series.length) return null;
		var w = section('Complaint volume by product segment',
			'Monthly complaints received, logarithmic scale. Hover for exact counts.');
		var months = d.volume.months;
		var series = d.volume.series.slice(0, 3);
		var all = [];
		series.forEach(function (s) {
			s.counts.forEach(function (v) { if (v > 0) all.push(Math.log10(v)); });
		});
		if (!all.length) return null;
		var lo = Math.floor(Math.min.apply(null, all));
		var hi = Math.ceil(Math.max.apply(null, all));
		var svg = frame('Monthly complaint volume by segment',
			'Credit reporting rises far above every other segment.');
		var ticks = [];
		for (var p = lo; p <= hi; p++) {
			ticks.push({
				v: p,
				label: p >= 6 ? '1M' : p >= 3 ? Math.pow(10, p - 3) + 'k' : String(Math.pow(10, p))
			});
		}
		gridY(svg, ticks, lo, hi);
		xLabels(svg, months.map(function (m) { return m.slice(0, 4); }), 24);
		series.forEach(function (s, i) {
			polyline(svg, s.counts.map(function (v) { return v > 0 ? Math.log10(v) : null; }),
				lo, hi, 'sppi-s' + (i + 1));
		});

		var fig = figureWrap(svg);
		makeInteractive(fig, svg, {
			labels: months, lo: lo, hi: hi,
			headline: function (i) { return monthLabel(months[i]); },
			series: series.map(function (s, i) {
				return {
					label: s.label, cls: 'sppi-s' + (i + 1),
					values: s.counts.map(function (v) { return v > 0 ? Math.log10(v) : null; }),
					format: function (v, idx) { return fmt(s.counts[idx]); }
				};
			})
		});
		w.appendChild(fig);
		w.appendChild(legend(series.map(function (s, i) {
			return { cls: 'sppi-s' + (i + 1), label: s.label };
		})));
		return w;
	}

	/* ---- map ---------------------------------------------------------- */

	function quantileBreaks(values, k) {
		var s = values.slice().sort(function (a, b) { return a - b; });
		var out = [];
		for (var i = 1; i < k; i++) out.push(s[Math.floor(i / k * s.length)]);
		return out;
	}

	function panelMap(d, mapUrl) {
		if (!d.states || !d.states.length) return null;
		var w = section('Where complaints come from',
			'Complaints per 100,000 residents over the last ' + d.meta.window_months +
			' complete months, and the share of each state’s narratives that are templated. ' +
			'States that file heavily file more of both kinds, so a high rate is not by itself ' +
			'evidence of coordination. Hover or tab through a state for its figures.');

		var byState = {};
		d.states.forEach(function (r) { byState[r.state] = r; });

		var modes = [
			{ key: 'per_100k', label: 'Complaints per 100k', fmt: function (v) { return fmt(Math.round(v)); } },
			{ key: 'templated_pct', label: 'Templated share', fmt: function (v) { return pct(v); } }
		];
		var mode = modes[0];

		var toggle = el('div', { class: 'sppi-mapmode', role: 'group', 'aria-label': 'Map measure' });
		var buttons = modes.map(function (m) {
			var b = el('button', { type: 'button', 'aria-pressed': m === mode ? 'true' : 'false' }, m.label);
			b.addEventListener('click', function () {
				mode = m;
				buttons.forEach(function (x, i) { x.setAttribute('aria-pressed', modes[i] === mode ? 'true' : 'false'); });
				paint();
			});
			toggle.appendChild(b);
			return b;
		});
		w.appendChild(toggle);

		// The map keeps its own width cap: its geometry is 960x600, so at the
		// full wide measure it would stand over 700px tall.
		var holder = el('figure', { class: 'sppi-figure sppi-figure--map' });
		holder.appendChild(el('p', { class: 'sppi-panel-note' }, 'Loading map…'));
		w.appendChild(holder);

		var scale = el('div', { class: 'sppi-scale' });
		w.appendChild(scale);

		var paths = {}, svg = null, tip = null;

		function paint() {
			if (!svg) return;
			var vals = d.states.map(function (r) { return r[mode.key]; })
				.filter(function (v) { return v !== null && v !== undefined; });
			var breaks = quantileBreaks(vals, 6);

			function bucket(v) {
				if (v === null || v === undefined) return -1;
				var i = 0;
				while (i < breaks.length && v >= breaks[i]) i++;
				return i;
			}

			Object.keys(paths).forEach(function (abbr) {
				var rec = byState[abbr];
				var node = paths[abbr];
				var b = rec ? bucket(rec[mode.key]) : -1;
				if (b < 0) {
					node.setAttribute('class', 'sppi-state is-empty');
					node.style.fill = '';
				} else {
					node.setAttribute('class', 'sppi-state');
					node.style.fill = seriesFill('--sppi-s1', 14 + b * 16, '47,116,181');
				}
			});

			scale.innerHTML = '';
			scale.appendChild(el('span', {}, 'Lower'));
			var bar = el('div', { class: 'sppi-scale-bar' });
			for (var i = 0; i < 6; i++) {
				var sw = el('i');
				sw.style.background = seriesFill('--sppi-s1', 14 + i * 16, '47,116,181');
				bar.appendChild(sw);
			}
			scale.appendChild(bar);
			scale.appendChild(el('span', {}, 'Higher'));
			scale.appendChild(el('span', {}, '· ' + mode.label));
		}

		function showTip(abbr, evt) {
			var rec = byState[abbr];
			var name = STATE_NAMES[abbr] || abbr;
			var body = '<div class="sppi-tip-head">' + name + '</div>';
			if (rec) {
				body += '<div class="sppi-tip-row">Complaints<span class="sppi-tip-val">' +
					fmt(rec.complaints) + '</span></div>' +
					'<div class="sppi-tip-row">Per 100k<span class="sppi-tip-val">' +
					fmt(Math.round(rec.per_100k)) + '</span></div>' +
					'<div class="sppi-tip-row">Templated<span class="sppi-tip-val">' +
					pct(rec.templated_pct) + '</span></div>';
			} else {
				body += '<div class="sppi-tip-row">No data</div>';
			}
			tip.innerHTML = body;
			tip.setAttribute('data-show', '1');

			var hr = holder.getBoundingClientRect();
			var x, y;
			if (evt && evt.clientX !== undefined) {
				x = evt.clientX - hr.left + 14;
				y = evt.clientY - hr.top + 14;
			} else {
				var br = paths[abbr].getBoundingClientRect();
				x = br.left - hr.left + br.width / 2 + 10;
				y = br.top - hr.top + br.height / 2;
			}
			if (x + tip.offsetWidth > hr.width - 4) x = hr.width - tip.offsetWidth - 4;
			if (y + tip.offsetHeight > hr.height - 4) y = hr.height - tip.offsetHeight - 4;
			tip.style.left = Math.max(4, x) + 'px';
			tip.style.top = Math.max(4, y) + 'px';
		}

		function hideTip() { tip.removeAttribute('data-show'); }

		fetch(mapUrl)
			.then(function (r) {
				if (!r.ok) throw new Error('HTTP ' + r.status);
				return r.json();
			})
			.then(function (geo) {
				holder.innerHTML = '';
				svg = svgEl('svg', {
					viewBox: geo.viewBox, class: 'sppi-map', role: 'img',
					'aria-label': 'Map of US states shaded by complaint rate'
				});
				svg.appendChild(svgEl('title', {}, 'US states shaded by complaint measure'));

				Object.keys(geo.states).forEach(function (abbr) {
					var rec = byState[abbr];
					var p = svgEl('path', {
						d: geo.states[abbr], class: 'sppi-state',
						tabindex: '0', role: 'img',
						'aria-label': (STATE_NAMES[abbr] || abbr) + (rec
							? ': ' + fmt(Math.round(rec.per_100k)) + ' complaints per 100,000 residents, ' +
							pct(rec.templated_pct) + ' templated'
							: ': no data')
					});
					p.addEventListener('pointermove', function (e) { showTip(abbr, e); });
					p.addEventListener('pointerleave', hideTip);
					p.addEventListener('focus', function () { showTip(abbr, null); });
					p.addEventListener('blur', hideTip);
					paths[abbr] = p;
					svg.appendChild(p);
				});

				Object.keys(geo.labels || {}).forEach(function (abbr) {
					if (NO_LABEL[abbr]) return;
					var xy = geo.labels[abbr];
					svg.appendChild(svgEl('text', {
						x: xy[0], y: xy[1] + 3, class: 'sppi-state-label',
						'text-anchor': 'middle'
					}, abbr));
				});

				holder.appendChild(svg);
				tip = el('div', { class: 'sppi-tip', role: 'status', 'aria-live': 'polite' });
				holder.appendChild(tip);
				paint();
			})
			.catch(function (e) {
				holder.innerHTML = '';
				holder.appendChild(el('p', { class: 'sppi-panel-note' },
					'The map could not be loaded; the table below carries the same figures.'));
				if (window.console) console.error('sppi-cfpb map:', e);
			});

		// The table is always rendered: it is the accessible equivalent of the
		// map and the fallback if the geometry fails to load.
		var top = d.states.slice(0, 12);
		w.appendChild(el('p', { class: 'sppi-panel-note sppi-prose' }, 'Highest-filing states:'));
		w.appendChild(dataTable(top, [
			{ label: 'State', get: function (r) { return STATE_NAMES[r.state] || r.state; } },
			{ label: 'Per 100k', num: true, get: function (r) { return fmt(Math.round(r.per_100k)); } },
			{ label: 'Complaints', num: true, get: function (r) { return fmt(r.complaints); } },
			{ label: 'Templated', num: true, get: function (r) { return pct(r.templated_pct); } }
		]));
		return w;
	}

	/* ---- tables ------------------------------------------------------- */

	/**
	 * A plain data table.
	 *
	 * Earlier versions drew a proportional bar behind the figures in a numeric
	 * column. It duplicated information the number already carried, competed
	 * with the charts above it for attention, and made the cell contents shift
	 * as the column resized. The number on its own is easier to read and to
	 * copy out.
	 */
	function dataTable(rows, cols) {
		var wrap = el('div', { class: 'sppi-tablewrap' });
		var t = el('table', { class: 'sppi-table' });
		var thead = el('thead'), tr = el('tr');
		cols.forEach(function (c) {
			tr.appendChild(el('th', { class: c.num ? 'sppi-num' : '', scope: 'col' }, c.label));
		});
		thead.appendChild(tr);
		t.appendChild(thead);
		var tb = el('tbody');
		rows.forEach(function (r) {
			var row = el('tr');
			cols.forEach(function (c) {
				var td = el('td', { class: c.num ? 'sppi-num' : '' });
				td.textContent = c.get(r);
				row.appendChild(td);
			});
			tb.appendChild(row);
		});
		t.appendChild(tb);
		wrap.appendChild(t);
		return wrap;
	}

	function panelCompanies(d) {
		if (!d.companies || !d.companies.length) return null;
		var w = section('Most-complained-about companies',
			'By complaints received over the last ' + d.meta.window_months +
			' complete months. Names are grouped across corporate variants.');
		var top = d.companies.slice(0, 12);
		w.appendChild(dataTable(top, [
			{ label: 'Company', get: function (r) { return r.company; } },
			{ label: 'Complaints', num: true, get: function (r) { return fmt(r.complaints); } },
			{ label: 'With narrative', num: true, get: function (r) { return fmt(r.narratives); } }
		]));
		return w;
	}

	function panelRelief(d) {
		if (!d.relief || !d.relief.length) return null;
		var win = d.relief_window || {};
		var w = section('Do complaints get results?',
			'Share of closed complaints resolved with relief, comparing templated filings with the rest, ' +
			(win.from ? 'over ' + monthLabel(win.from) + ' to ' + monthLabel(win.to) + '. ' : '') +
			'Relief here is overwhelmingly non-monetary — in credit reporting, a corrected or deleted entry.');
		var rows = d.relief.filter(function (r) {
			return r.templated && r.templated.relief_pct !== null &&
				r.organic && r.organic.relief_pct !== null;
		}).slice(0, 6);
		if (!rows.length) return null;
		w.appendChild(dataTable(rows, [
			{ label: 'Segment', get: function (r) { return r.label; } },
			{ label: 'Templated', num: true, get: function (r) { return pct(r.templated.relief_pct); } },
			{ label: 'Organic', num: true, get: function (r) { return pct(r.organic.relief_pct); } },
			{ label: 'Closed', num: true, get: function (r) { return fmt(r.templated.closed + r.organic.closed); } }
		]));
		return w;
	}

	function footer(d) {
		var f = el('div', { class: 'sppi-foot' });
		f.appendChild(el('p', { class: 'sppi-prose' },
			'Data through ' + d.meta.data_through + '. Source: ' + d.meta.source +
			'. A complaint counts as templated when its narrative, after normalising case, ' +
			'punctuation and the Bureau’s redaction markers, is identical to at least ' +
			(d.meta.template_threshold - 1) + ' others. Templating describes who drafted a ' +
			'complaint, not whether the underlying grievance is valid.'));
		f.appendChild(el('p', { class: 'sppi-prose' }, 'Analysis: ' + d.meta.publisher +
			'. Payload generated ' + d.meta.generated + '.'));
		return f;
	}

	/* ------------------------------------------------------------------ */

	function render(mount, data, panels, mapUrl) {
		var PANELS = {
			headline: function (d) { return panelHeadline(d); },
			trend: function (d) { return panelTrend(d); },
			volume: function (d) { return panelVolume(d); },
			states: function (d) { return panelMap(d, mapUrl); },
			companies: function (d) { return panelCompanies(d); },
			relief: function (d) { return panelRelief(d); }
		};
		mount.innerHTML = '';
		(panels && panels.length ? panels : Object.keys(PANELS)).forEach(function (name) {
			var fn = PANELS[name];
			if (!fn) return;
			var node;
			try {
				node = fn(data);
			} catch (e) {
				// One malformed panel must not blank the whole dashboard.
				if (window.console) console.error('sppi-cfpb panel failed:', name, e);
				return;
			}
			if (node) mount.appendChild(node);
		});
		mount.appendChild(footer(data));
	}

	function boot() {
		var mounts = document.querySelectorAll('.sppi-cfpb-mount');
		if (!mounts.length) return;
		var cfg = window.SPPI_CFPB || {};
		var wrapper = mounts[0].parentNode;
		var mapUrl = cfg.mapUrl || wrapper.getAttribute('data-map') || DEFAULT_MAP;

		// Panel titles have to slot into the outline of whatever page hosts
		// them, so the level is the host's decision, not this file's.
		var lvl = String(cfg.heading || wrapper.getAttribute('data-heading') || '').toLowerCase();
		if (/^h[1-6]$/.test(lvl)) HEADING = lvl;

		if (cfg.data) {
			Array.prototype.forEach.call(mounts, function (m) {
				render(m, cfg.data, cfg.panels, mapUrl);
			});
			return;
		}
		var feed = wrapper.getAttribute('data-feed') || DEFAULT_FEED;
		fetch(feed)
			.then(function (r) {
				if (!r.ok) throw new Error('HTTP ' + r.status);
				return r.json();
			})
			.then(function (data) {
				Array.prototype.forEach.call(mounts, function (m) {
					var p = (m.parentNode.getAttribute('data-panels') || '').split(',').filter(Boolean);
					render(m, data, p, mapUrl);
				});
			})
			.catch(function (e) {
				Array.prototype.forEach.call(mounts, function (m) {
					m.innerHTML = '';
					m.appendChild(el('p', { class: 'sppi-cfpb-error' },
						'The complaint dashboard could not be loaded.'));
				});
				if (window.console) console.error(e);
			});
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', boot);
	} else {
		boot();
	}
})();
