// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

        (function () {
            // --- 1. MOCK DATA LOGIC (Runs if template tags are detected) ---
            function checkAndMockData() {
                const usernameEl = document.getElementById('username');
                const rawContent = usernameEl ? usernameEl.textContent.trim() : '';

                if (rawContent.includes('{{') || rawContent === '') {
                    console.log("Template tags detected. Activating Preview Mode with Mock Data.");
                    document.getElementById('username').textContent = "User_12345";
                    document.getElementById('expiry').textContent = "2025/12/30";

                    const statusWrapper = document.getElementById('template-status-wrapper');
                    if (statusWrapper) {
                        const statusBadge = document.getElementById('status-display');
                        statusBadge.innerHTML = `<span class="status-dot"></span><span id="status-text">Active</span>`;
                        statusBadge.className = 'status-badge active';
                    }

                    const linksList = document.getElementById('links-list');
                    if (linksList) {
                        linksList.innerHTML = '';
                        const mockLinks = [
                            { name: "Germany", link: "#" },
                            { name: "France", link: "#" },
                            { name: "Netherlands", link: "#" }
                        ];
                        const nodeIco = `<span class="node-ico"><svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/></svg></span>`;
                        const dlIco = `<div class="btn-icon-container"><svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg></div>`;
                        mockLinks.forEach(item => {
                            const a = document.createElement('a');
                            a.className = 'download-btn';
                            a.href = item.link;
                            a.setAttribute('download', '');
                            a.innerHTML = `${nodeIco}<span class="node-meta"><span class="node-name">${item.name}</span><span class="node-sub">OpenVPN · .ovpn</span></span>${dlIco}`;
                            linksList.appendChild(a);
                        });
                    }
                } else {
                    const statusWrapper = document.getElementById('template-status-wrapper');
                    const statusBadge = document.getElementById('status-display');
                    if (statusWrapper && statusBadge) {
                        const isActive = statusWrapper.querySelector('.active-text') !== null;
                        if (isActive) {
                            statusBadge.classList.add('active');
                            statusBadge.innerHTML = `<span class="status-dot"></span><span id="status-text">Active</span>`;
                        } else if (statusWrapper.querySelector('.inactive-text') !== null) {
                            statusBadge.classList.add('inactive');
                            statusBadge.innerHTML = `<span class="status-dot"></span><span id="status-text">Inactive</span>`;
                        }
                    }
                }
            }

            // --- 2. LANGUAGE DATA ---
            const langData = {
                fa: {
                    title: "اتصال شما",
                    brandSub: "دسترسی امن",
                    username: "نام کاربری",
                    totalTraffic: "ترافیک کل",
                    expiry: "انقضا",
                    daysLeft: "روز باقی‌مانده",
                    usage: "مصرف داده",
                    active: "فعال",
                    inactive: "غیرفعال",
                    links: "دانلود کانفیگ",
                    noLinks: "در حال حاضر کانفیگی موجود نیست. لطفاً با پشتیبانی تماس بگیرید.",
                    howtoTitle: "نحوه اتصال:",
                    howtoBody: "یک کانفیگ را دانلود کنید، در اپلیکیشن OpenVPN باز کرده و روی اتصال بزنید. اپلیکیشن را از دکمه پایین بگیرید.",
                    client: "دریافت اپلیکیشن OpenVPN",
                    footer: "این کانفیگ شخصی OpenVPN شماست. آن را محرمانه نگه دارید — هر کسی با این فایل می‌تواند از اتصال شما استفاده کند.",
                    nodeSub: "OpenVPN · .ovpn",
                    dir: "rtl",
                    themeLight: "روشن", themeDark: "تاریک", themeSystem: "سیستم"
                },
                en: {
                    title: "Your Connection",
                    brandSub: "Secure Access",
                    username: "Username",
                    totalTraffic: "Total Traffic",
                    expiry: "Expires",
                    daysLeft: "Days Left",
                    usage: "Data Usage",
                    active: "Active",
                    inactive: "Inactive",
                    links: "Download Your Config",
                    noLinks: "No configs are available right now. Please contact support.",
                    howtoTitle: "How to connect:",
                    howtoBody: "Download a config below, open it in the OpenVPN app, and tap connect. Need the app? Use the button at the bottom.",
                    client: "Get the OpenVPN App",
                    footer: "This is your personal OpenVPN config. Keep it private — anyone with this file can use your connection.",
                    nodeSub: "OpenVPN · .ovpn",
                    dir: "ltr",
                    themeLight: "Light", themeDark: "Dark", themeSystem: "System"
                },
                ru: {
                    title: "Ваше подключение",
                    brandSub: "Безопасный доступ",
                    username: "Имя пользователя",
                    totalTraffic: "Всего трафика",
                    expiry: "Истекает",
                    daysLeft: "Осталось дней",
                    usage: "Использовано",
                    active: "Активен",
                    inactive: "Неактивен",
                    links: "Скачать конфиг",
                    noLinks: "Конфигурации пока недоступны. Свяжитесь с поддержкой.",
                    howtoTitle: "Как подключиться:",
                    howtoBody: "Скачайте конфиг ниже, откройте его в приложении OpenVPN и нажмите «Подключить». Приложение — кнопкой внизу.",
                    client: "Скачать OpenVPN",
                    footer: "Это ваш личный конфиг OpenVPN. Храните его в тайне — любой с этим файлом сможет использовать ваше подключение.",
                    nodeSub: "OpenVPN · .ovpn",
                    dir: "ltr",
                    themeLight: "Светлая", themeDark: "Тёмная", themeSystem: "Системная"
                },
                zh: {
                    title: "您的连接",
                    brandSub: "安全访问",
                    username: "用户名",
                    totalTraffic: "总流量",
                    expiry: "到期",
                    daysLeft: "剩余天数",
                    usage: "流量使用",
                    active: "有效",
                    inactive: "无效",
                    links: "下载配置",
                    noLinks: "暂时没有可用配置，请联系客服。",
                    howtoTitle: "如何连接：",
                    howtoBody: "下载下面的配置，用 OpenVPN 客户端打开并点击连接。需要客户端？用底部按钮获取。",
                    client: "获取 OpenVPN 客户端",
                    footer: "这是您的个人 OpenVPN 配置。请妥善保管——任何拥有此文件的人都能使用您的连接。",
                    nodeSub: "OpenVPN · .ovpn",
                    dir: "ltr",
                    themeLight: "浅色", themeDark: "深色", themeSystem: "系统"
                }
            };

            // --- 3. THEME ICONS ---
            const icons = {
                light: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />',
                dark: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />',
                system: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />'
            };

            // --- 4. CORE UI FUNCTIONS ---
            function updateUI(lang, themePref) {
                const dict = langData[lang];
                document.getElementById('title').textContent = dict.title;
                document.getElementById('brand-sub').textContent = dict.brandSub;
                document.getElementById('username-label').textContent = dict.username;
                document.getElementById('total-traffic-label').textContent = dict.totalTraffic;
                document.getElementById('expiry-label').textContent = dict.expiry;
                document.getElementById('days-left-label').textContent = dict.daysLeft;
                document.getElementById('usage-label').textContent = dict.usage;
                document.getElementById('links-label').textContent = dict.links;
                const noLinksText = document.getElementById('no-links-text');
                if (noLinksText) noLinksText.textContent = dict.noLinks;
                document.getElementById('howto-title').textContent = dict.howtoTitle;
                document.getElementById('howto-body').textContent = dict.howtoBody;
                document.getElementById('client-text').textContent = dict.client;
                document.getElementById('footer-note').textContent = dict.footer;
                // node subtitle on each card
                document.querySelectorAll('.node-sub').forEach(el => el.textContent = dict.nodeSub);

                const themeItems = document.querySelectorAll('#theme-dropdown .dropdown-item');
                themeItems.forEach(item => {
                    const t = item.dataset.theme;
                    const label = t === 'light' ? dict.themeLight : (t === 'dark' ? dict.themeDark : dict.themeSystem);
                    item.childNodes.forEach(n => {
                        if (n.nodeType === 3 && n.textContent.trim().length > 0) n.textContent = " " + label;
                    });
                });

                const statusText = document.getElementById('status-text');
                if (statusText) {
                    const isActive = document.getElementById('status-display').classList.contains('active');
                    statusText.textContent = isActive ? dict.active : dict.inactive;
                }

                document.documentElement.lang = lang;
                document.documentElement.dir = dict.dir;

                const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                let effectiveTheme = themePref;
                if (themePref === 'system') effectiveTheme = systemDark ? 'dark' : 'light';
                document.documentElement.setAttribute('data-theme', effectiveTheme);

                const svg = document.querySelector('.theme-icon-display');
                svg.innerHTML = icons[themePref === 'system' ? 'system' : effectiveTheme];

                document.querySelectorAll('.dropdown-item').forEach(btn => btn.classList.remove('selected'));
                document.querySelector(`[data-lang="${lang}"]`)?.classList.add('selected');
                document.querySelector(`[data-theme="${themePref}"]`)?.classList.add('selected');

                // Color the usage bar by level
                const usageFill = document.getElementById('usage-fill');
                const pctText = (document.getElementById('usage-pct')?.textContent || '').replace('%', '').trim();
                if (usageFill && pctText && !isNaN(pctText)) {
                    const p = parseInt(pctText, 10);
                    usageFill.classList.toggle('warn', p >= 75 && p < 90);
                    usageFill.classList.toggle('danger', p >= 90);
                }

                localStorage.setItem('sub_lang', lang);
                localStorage.setItem('sub_theme', themePref);
            }

            // --- 5. DROPDOWN LOGIC ---
            function setupDropdown(id) {
                const container = document.getElementById(id);
                const btn = container.querySelector('.icon-btn');
                btn.onclick = (e) => {
                    e.stopPropagation();
                    document.querySelectorAll('.dropdown').forEach(d => {
                        if (d !== container) d.classList.remove('open');
                    });
                    container.classList.toggle('open');
                    btn.classList.toggle('active');
                };
            }
            setupDropdown('lang-dropdown');
            setupDropdown('theme-dropdown');

            document.addEventListener('click', () => {
                document.querySelectorAll('.dropdown').forEach(d => {
                    d.classList.remove('open');
                    d.querySelector('.icon-btn').classList.remove('active');
                });
            });

            document.querySelectorAll('#lang-dropdown .dropdown-item').forEach(item => {
                item.onclick = () => {
                    const l = item.dataset.lang;
                    const currentTheme = localStorage.getItem('sub_theme') || 'system';
                    updateUI(l, currentTheme);
                };
            });

            document.querySelectorAll('#theme-dropdown .dropdown-item').forEach(item => {
                item.onclick = () => {
                    const t = item.dataset.theme;
                    const currentLang = localStorage.getItem('sub_lang') || 'fa';
                    updateUI(currentLang, t);
                };
            });

            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
                const currentThemePref = localStorage.getItem('sub_theme') || 'system';
                if (currentThemePref === 'system') {
                    const currentLang = localStorage.getItem('sub_lang') || 'fa';
                    updateUI(currentLang, 'system');
                }
            });

            // --- 6. INITIALIZATION ---
            checkAndMockData();
            const savedLang = localStorage.getItem('sub_lang') || 'fa';
            const savedTheme = localStorage.getItem('sub_theme') || 'system';
            updateUI(savedLang, savedTheme);
        })();
