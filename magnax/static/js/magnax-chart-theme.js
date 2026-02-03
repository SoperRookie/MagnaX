/**
 * MagnaX Highcharts Dark Theme - Grafana Style
 * A professional dark theme for Highcharts/Highstock charts
 */

(function() {
    'use strict';

    // Define color palette - Enhanced brightness for better visibility
    var colors = {
        // Background colors
        canvasBg: '#111217',
        mainBg: '#181b1f',
        cardBg: '#1e2128',
        inputBg: '#2a2e37',

        // Border colors
        borderWeak: '#2a2e37',
        borderMedium: '#3d4453',

        // Text colors
        textPrimary: '#e8e9ea',
        textSecondary: '#adb5c1',
        textDisabled: '#6e7681',

        // Accent colors - Brighter for dark background
        accentGreen: '#8dd17a',
        accentBlue: '#5c9cf5',
        accentOrange: '#ffab4a',
        accentRed: '#ff6b7a',
        accentPurple: '#c99ae8',
        accentYellow: '#ffeb5c',
        accentCyan: '#33e8d8',
        accentGold: '#ffc933',

        // Chart series colors - Enhanced brightness and saturation
        cpu: '#8dd17a',        // Bright green
        memory: '#6ba8ff',     // Bright blue
        networkTx: '#ffab4a',  // Bright orange
        networkRx: '#c99ae8',  // Bright purple
        fps: '#ffeb5c',        // Bright yellow
        gpu: '#33e8d8',        // Bright cyan
        battery: '#ffc933'     // Bright gold
    };

    // Series colors for charts
    var seriesColors = [
        colors.cpu,        // Green - CPU
        colors.memory,     // Blue - Memory
        colors.networkTx,  // Orange - Network TX
        colors.networkRx,  // Purple - Network RX
        colors.fps,        // Yellow - FPS
        colors.gpu,        // Cyan - GPU
        colors.battery,    // Gold - Battery
        colors.accentRed   // Red - Errors/Warnings
    ];

    // MagnaX Dark Theme for Highcharts
    var magnaxDarkTheme = {
        colors: seriesColors,

        chart: {
            backgroundColor: colors.cardBg,
            borderColor: colors.borderWeak,
            borderWidth: 0,
            borderRadius: 4,
            plotBackgroundColor: colors.cardBg,
            plotBorderColor: colors.borderWeak,
            plotBorderWidth: 0,
            style: {
                fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
            },
            resetZoomButton: {
                theme: {
                    fill: colors.inputBg,
                    stroke: colors.borderMedium,
                    r: 4,
                    style: {
                        color: colors.textPrimary,
                        fontWeight: '500',
                        fontSize: '12px'
                    },
                    states: {
                        hover: {
                            fill: colors.accentBlue,
                            stroke: colors.accentBlue,
                            style: {
                                color: '#ffffff'
                            }
                        }
                    }
                }
            }
        },

        title: {
            style: {
                color: colors.textPrimary,
                fontSize: '15px',
                fontWeight: '600'
            }
        },

        subtitle: {
            style: {
                color: colors.textSecondary,
                fontSize: '12px'
            }
        },

        xAxis: {
            gridLineColor: 'rgba(255, 255, 255, 0.1)',
            gridLineWidth: 0,
            lineColor: '#999',
            tickColor: '#999',
            labels: {
                style: {
                    color: '#FFF',
                    fontWeight: 'bold'
                }
            },
            title: {
                style: {
                    color: '#FFF',
                    font: 'bold 12px Lucida Grande, Lucida Sans Unicode, Verdana, Arial, Helvetica, sans-serif'
                }
            },
            crosshair: {
                color: colors.borderMedium,
                width: 1
            }
        },

        yAxis: {
            gridLineColor: 'rgba(255, 255, 255, 0.1)',
            gridLineWidth: 1,
            lineColor: '#999',
            tickColor: '#999',
            lineWidth: 0,
            tickWidth: 0,
            labels: {
                style: {
                    color: '#FFF',
                    fontWeight: 'bold'
                }
            },
            title: {
                style: {
                    color: '#FFF',
                    font: 'bold 12px Lucida Grande, Lucida Sans Unicode, Verdana, Arial, Helvetica, sans-serif'
                }
            },
            alternateGridColor: null,
            minorGridLineColor: 'rgba(255,255,255,0.07)'
        },

        tooltip: {
            backgroundColor: '#1e2128',
            borderColor: '#3d4453',
            borderRadius: 6,
            borderWidth: 1,
            shadow: {
                color: 'rgba(0, 0, 0, 0.5)',
                offsetX: 2,
                offsetY: 3,
                width: 6
            },
            style: {
                color: '#ffffff',
                fontSize: '13px',
                fontWeight: '500'
            },
            headerFormat: '<span style="font-size: 12px; color: #ffffff; font-weight: 600;">{point.key}</span><br/>',
            pointFormat: '<span style="color:{series.color}; font-size: 14px;">\u25CF</span> <span style="color: #cccccc">{series.name}:</span> <b style="color: #ffffff">{point.y}</b><br/>'
        },

        legend: {
            backgroundColor: 'transparent',
            borderColor: 'transparent',
            borderWidth: 0,
            itemStyle: {
                color: colors.textPrimary,
                fontSize: '12px',
                fontWeight: '500'
            },
            itemHoverStyle: {
                color: colors.accentGreen
            },
            itemHiddenStyle: {
                color: colors.textDisabled
            },
            title: {
                style: {
                    color: colors.textPrimary,
                    fontWeight: '600'
                }
            }
        },

        plotOptions: {
            series: {
                lineWidth: 2.5,
                animation: false,
                dataLabels: {
                    style: {
                        color: colors.textPrimary,
                        textOutline: 'none'
                    }
                },
                marker: {
                    enabled: false,
                    lineColor: colors.cardBg,
                    radius: 3,
                    states: {
                        hover: {
                            enabled: true,
                            radius: 5
                        }
                    }
                },
                states: {
                    hover: {
                        lineWidth: 3.5
                    }
                }
            },
            line: {
                lineWidth: 2.5,
                states: {
                    hover: {
                        lineWidth: 3.5
                    }
                }
            },
            spline: {
                lineWidth: 2.5,
                states: {
                    hover: {
                        lineWidth: 3.5
                    }
                }
            },
            area: {
                fillOpacity: 0.25,
                lineWidth: 2.5
            },
            areaspline: {
                fillOpacity: 0.25,
                lineWidth: 2.5
            },
            column: {
                borderWidth: 0,
                borderRadius: 2
            },
            bar: {
                borderWidth: 0,
                borderRadius: 2
            },
            pie: {
                borderWidth: 0,
                dataLabels: {
                    color: colors.textPrimary
                }
            },
            boxplot: {
                fillColor: colors.inputBg
            },
            candlestick: {
                lineColor: colors.textPrimary
            },
            errorbar: {
                color: colors.textSecondary
            }
        },

        credits: {
            enabled: false
        },

        loading: {
            labelStyle: {
                color: colors.textPrimary
            },
            style: {
                backgroundColor: colors.cardBg
            }
        },

        drilldown: {
            activeAxisLabelStyle: {
                color: colors.textSecondary
            },
            activeDataLabelStyle: {
                color: colors.textPrimary
            }
        },

        // Navigator (for stock charts)
        navigator: {
            enabled: true,
            handles: {
                backgroundColor: colors.inputBg,
                borderColor: colors.borderMedium
            },
            outlineColor: colors.borderWeak,
            outlineWidth: 1,
            maskFill: 'rgba(50, 116, 217, 0.1)',
            series: {
                color: colors.accentBlue,
                fillOpacity: 0.2,
                lineColor: colors.accentBlue,
                lineWidth: 1
            },
            xAxis: {
                gridLineColor: colors.borderWeak,
                labels: {
                    style: {
                        color: colors.textDisabled
                    }
                }
            }
        },

        // Scrollbar
        scrollbar: {
            enabled: true,
            barBackgroundColor: colors.inputBg,
            barBorderColor: colors.borderWeak,
            barBorderWidth: 1,
            barBorderRadius: 3,
            buttonBackgroundColor: colors.inputBg,
            buttonBorderColor: colors.borderWeak,
            buttonBorderWidth: 1,
            buttonBorderRadius: 3,
            buttonArrowColor: colors.textSecondary,
            rifleColor: colors.textDisabled,
            trackBackgroundColor: colors.mainBg,
            trackBorderColor: colors.borderWeak,
            trackBorderWidth: 1,
            trackBorderRadius: 3
        },

        // Range selector (for stock charts)
        rangeSelector: {
            buttonTheme: {
                fill: colors.inputBg,
                stroke: colors.borderMedium,
                strokeWidth: 1,
                r: 4,
                style: {
                    color: colors.textPrimary,
                    fontWeight: '500',
                    fontSize: '12px'
                },
                states: {
                    hover: {
                        fill: colors.borderMedium,
                        stroke: colors.accentBlue,
                        style: {
                            color: colors.textPrimary
                        }
                    },
                    select: {
                        fill: colors.accentBlue,
                        stroke: colors.accentBlue,
                        style: {
                            color: '#ffffff',
                            fontWeight: '600'
                        }
                    },
                    disabled: {
                        fill: colors.mainBg,
                        stroke: colors.borderWeak,
                        style: {
                            color: colors.textDisabled
                        }
                    }
                }
            },
            inputBoxBorderColor: colors.borderMedium,
            inputBoxWidth: 100,
            inputStyle: {
                backgroundColor: colors.inputBg,
                color: colors.textPrimary,
                fontWeight: '500'
            },
            labelStyle: {
                color: colors.textPrimary,
                fontWeight: '500'
            }
        },

        // Exporting
        exporting: {
            buttons: {
                contextButton: {
                    symbolFill: colors.textPrimary,
                    symbolStroke: colors.textPrimary,
                    symbolStrokeWidth: 2,
                    theme: {
                        fill: colors.inputBg,
                        stroke: colors.borderMedium,
                        r: 4,
                        states: {
                            hover: {
                                fill: colors.borderMedium,
                                stroke: colors.accentBlue
                            },
                            select: {
                                fill: colors.accentBlue,
                                stroke: colors.accentBlue
                            }
                        }
                    }
                }
            },
            menuStyle: {
                background: colors.cardBg,
                border: '1px solid ' + colors.borderMedium,
                boxShadow: '0 4px 12px rgba(0, 0, 0, 0.4)'
            },
            menuItemStyle: {
                color: colors.textPrimary,
                fontWeight: '500',
                fontSize: '13px',
                padding: '8px 16px'
            },
            menuItemHoverStyle: {
                background: colors.inputBg,
                color: colors.accentGreen
            }
        },

        // Navigation (for annotations)
        navigation: {
            menuItemStyle: {
                color: colors.textPrimary
            },
            menuItemHoverStyle: {
                background: colors.inputBg
            }
        },

        // Labels (for annotations)
        labels: {
            style: {
                color: colors.textPrimary
            }
        }
    };

    // Apply theme
    Highcharts.setOptions(magnaxDarkTheme);

    // Export color constants for external use
    window.MagnaxChartColors = colors;

    // Helper function to get chart color by metric type
    window.getMagnaxChartColor = function(metricType) {
        var colorMap = {
            'cpu': colors.cpu,
            'memory': colors.memory,
            'mem': colors.memory,
            'network': colors.networkTx,
            'network_tx': colors.networkTx,
            'network_rx': colors.networkRx,
            'upload': colors.networkTx,
            'download': colors.networkRx,
            'fps': colors.fps,
            'gpu': colors.gpu,
            'battery': colors.battery,
            'temperature': colors.accentRed,
            'temp': colors.accentRed
        };
        return colorMap[metricType.toLowerCase()] || colors.accentBlue;
    };

    // Helper function to create gradient fill for area charts
    window.createMagnaxGradient = function(color, opacity) {
        opacity = opacity || 0.2;
        return {
            linearGradient: { x1: 0, x2: 0, y1: 0, y2: 1 },
            stops: [
                [0, Highcharts.color(color).setOpacity(opacity).get('rgba')],
                [1, Highcharts.color(color).setOpacity(0).get('rgba')]
            ]
        };
    };

    console.log('MagnaX Highcharts Dark Theme loaded successfully');

})();
