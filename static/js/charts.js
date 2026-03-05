/* ============================================================
   Retirement Income Planner V2.0 — Chart.js Rendering
   Supports dynamic number of pots/accounts
   ============================================================ */

/**
 * Format a number as £X,XXX for chart tooltips/axes
 */
function formatMoney(value) {
    if (value >= 1000000) return '£' + (value / 1000000).toFixed(1) + 'M';
    if (value >= 1000) return '£' + (value / 1000).toFixed(0) + 'k';
    return '£' + value.toFixed(0);
}

/**
 * Color palette that cycles for any number of pots
 */
var POT_COLORS = [
    { border: '#198754', bg: 'rgba(25, 135, 84, 0.15)' },   // green
    { border: '#ffc107', bg: 'rgba(255, 193, 7, 0.15)' },   // amber
    { border: '#6f42c1', bg: 'rgba(111, 66, 193, 0.15)' },  // purple
    { border: '#fd7e14', bg: 'rgba(253, 126, 20, 0.15)' },  // orange
    { border: '#20c997', bg: 'rgba(32, 201, 151, 0.15)' },  // teal
    { border: '#e83e8c', bg: 'rgba(232, 62, 140, 0.15)' },  // pink
    { border: '#17a2b8', bg: 'rgba(23, 162, 184, 0.15)' },  // cyan
    { border: '#6c757d', bg: 'rgba(108, 117, 125, 0.15)' }, // grey
];

/**
 * Render a line chart for capital trajectory with dynamic pots.
 * @param {string} canvasId - The canvas element ID
 * @param {object} data - { labels, pots: [{name, data}], total }
 *   - pots is an array of { name: string, data: number[] }
 *   - total is number[]
 */
function renderCapitalChart(canvasId, data) {
    var ctx = document.getElementById(canvasId);
    if (!ctx) return;

    var datasets = [];

    // Total capital line (always first, on top)
    datasets.push({
        label: 'Total Capital',
        data: data.total,
        borderColor: '#0d6efd',
        backgroundColor: 'rgba(13, 110, 253, 0.08)',
        borderWidth: 3,
        fill: false,
        pointRadius: 3,
        pointHoverRadius: 6,
        tension: 0.1,
        order: 0
    });

    // Dynamic pot datasets
    if (data.pots && data.pots.length > 0) {
        data.pots.forEach(function(pot, idx) {
            var colorIdx = idx % POT_COLORS.length;
            datasets.push({
                label: pot.name,
                data: pot.data,
                borderColor: POT_COLORS[colorIdx].border,
                backgroundColor: POT_COLORS[colorIdx].bg,
                borderWidth: 2,
                fill: true,
                pointRadius: 2,
                tension: 0.1,
                order: idx + 1
            });
        });
    }

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.labels,
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    position: 'top',
                    labels: { usePointStyle: true, padding: 15 }
                },
                tooltip: {
                    callbacks: {
                        title: function(items) {
                            return 'Age ' + items[0].label;
                        },
                        label: function(context) {
                            return context.dataset.label + ': £' +
                                   context.parsed.y.toLocaleString('en-GB', {maximumFractionDigits: 0});
                        }
                    }
                }
            },
            scales: {
                x: {
                    title: { display: true, text: 'Age', font: { weight: 'bold' } },
                    grid: { display: false }
                },
                y: {
                    title: { display: true, text: 'Balance (£)', font: { weight: 'bold' } },
                    ticks: {
                        callback: function(value) { return formatMoney(value); }
                    },
                    beginAtZero: true
                }
            }
        }
    });
}

/**
 * Render a comparison line chart (multiple scenarios overlaid)
 * @param {string} canvasId - The canvas element ID
 * @param {array} labels - Age labels
 * @param {array} datasets - Chart.js dataset objects
 */
function renderCompareChart(canvasId, labels, datasets) {
    var ctx = document.getElementById(canvasId);
    if (!ctx) return;

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    position: 'top',
                    labels: { usePointStyle: true, padding: 15 }
                },
                tooltip: {
                    callbacks: {
                        title: function(items) {
                            return 'Age ' + items[0].label;
                        },
                        label: function(context) {
                            return context.dataset.label + ': £' +
                                   context.parsed.y.toLocaleString('en-GB', {maximumFractionDigits: 0});
                        }
                    }
                }
            },
            scales: {
                x: {
                    title: { display: true, text: 'Age', font: { weight: 'bold' } },
                    grid: { display: false }
                },
                y: {
                    title: { display: true, text: 'Total Capital (£)', font: { weight: 'bold' } },
                    ticks: {
                        callback: function(value) { return formatMoney(value); }
                    },
                    beginAtZero: true
                }
            }
        }
    });
}

/**
 * Render a horizontal bar chart (for optimiser comparisons)
 * @param {string} canvasId - The canvas element ID
 * @param {object} data - { labels, values, label, color }
 */
function renderBarChart(canvasId, data) {
    var ctx = document.getElementById(canvasId);
    if (!ctx) return;

    // Generate colors: first bar highlighted, rest muted
    var colors = data.values.map(function(v, i) {
        return i === 0 ? data.color : data.color + '80';  // 50% opacity for non-winners
    });

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.labels,
            datasets: [{
                label: data.label,
                data: data.values,
                backgroundColor: colors,
                borderColor: data.color,
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            indexAxis: 'y',
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return '£' + context.parsed.x.toLocaleString('en-GB', {maximumFractionDigits: 0});
                        }
                    }
                }
            },
            scales: {
                x: {
                    ticks: {
                        callback: function(value) { return formatMoney(value); }
                    },
                    beginAtZero: true
                },
                y: {
                    grid: { display: false }
                }
            }
        }
    });
}
