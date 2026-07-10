/* ══════════════════════════════════════════════════════════════
   HOBAN FDS - API 키 설정 모듈 (settings.js)
   - Gemini API 키를 localStorage에 저장/관리하고,
     LLM 관련 API 호출 시 자동으로 헤더를 주입한다.
   - 완전히 독립적인 모듈: 템플릿에 별도 HTML을 추가할 필요 없이
     이 스크립트를 로드하기만 하면 설정 모달/버튼이 자동으로 구성된다.
   ══════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    if (window.__fdsSettingsLoaded) return; // 중복 로드 방지
    window.__fdsSettingsLoaded = true;

    /* ────────────────────────────────────────────
       1. localStorage 키 & 기본값
       ──────────────────────────────────────────── */
    var STORAGE_KEYS = {
        geminiKey: 'fds_gemini_api_key',
        geminiModel: 'fds_gemini_model',
        geminiUrl: 'fds_gemini_api_url'
    };

    var DEFAULTS = {
        geminiModel: 'Gemini_3.1_Pro',
        geminiUrl: 'https://workspace.kr.pwc.com/api/workspace/coding_agent/v1/chat/completions'
    };

    function getStored(key, fallback) {
        try {
            var v = window.localStorage.getItem(key);
            return (v !== null && v !== undefined && v !== '') ? v : (fallback || '');
        } catch (e) {
            return fallback || '';
        }
    }

    function setStored(key, value) {
        try {
            if (value) {
                window.localStorage.setItem(key, value);
            } else {
                window.localStorage.removeItem(key);
            }
        } catch (e) {
            /* localStorage 접근 불가 (프라이빗 모드 등) - 조용히 무시 */
        }
    }

    /* ────────────────────────────────────────────
       2. window.getLLMHeaders()
       ──────────────────────────────────────────── */
    function getLLMHeaders() {
        var headers = {};

        var geminiKey = getStored(STORAGE_KEYS.geminiKey, '');
        if (geminiKey) {
            headers['X-Gemini-API-Key'] = geminiKey;
            headers['X-Gemini-Model'] = getStored(STORAGE_KEYS.geminiModel, DEFAULTS.geminiModel);
            headers['X-Gemini-API-URL'] = getStored(STORAGE_KEYS.geminiUrl, DEFAULTS.geminiUrl);
        }

        return headers;
    }
    window.getLLMHeaders = getLLMHeaders;

    /* ────────────────────────────────────────────
       3. window.fetch 오버라이드
       ──────────────────────────────────────────── */
    var ORIGINAL_FETCH = window.fetch ? window.fetch.bind(window) : null;

    // 각 규칙: path 판별 함수 + 필요한 provider('gemini' | 'anthropic')
    var LLM_ROUTES = [
        { test: function (p, m) { return m === 'POST' && p === '/api/chat'; }, provider: 'gemini' },
        { test: function (p, m) { return m === 'POST' && p === '/api/receipt'; }, provider: 'gemini' },
        { test: function (p, m) { return m === 'POST' && p.indexOf('/api/ocr-reparse/') === 0; }, provider: 'gemini' },
        { test: function (p, m) { return m === 'POST' && p === '/api/evidence/parse-document'; }, provider: 'gemini' },
        { test: function (p, m) { return m === 'POST' && p === '/api/evidence/parse-linked-doc'; }, provider: 'gemini' },
        { test: function (p, m) { return m === 'POST' && p === '/api/rules/parse-nl'; }, provider: 'gemini' },
        // /api/evidence/*/reparse, /api/evidence/{id} (POST only) 포함
        { test: function (p, m) { return m === 'POST' && p.indexOf('/api/evidence/') === 0; }, provider: 'gemini' },
        // /api/linked-doc/{docNo} (POST only)
        { test: function (p, m) { return m === 'POST' && p.indexOf('/api/linked-doc/') === 0; }, provider: 'gemini' }
    ];

    function resolveMethod(input, init) {
        if (init && init.method) return String(init.method).toUpperCase();
        if (typeof Request !== 'undefined' && input instanceof Request && input.method) {
            return String(input.method).toUpperCase();
        }
        return 'GET';
    }

    function resolvePath(input) {
        try {
            var raw = (typeof Request !== 'undefined' && input instanceof Request) ? input.url : input;
            return new URL(raw, window.location.origin).pathname;
        } catch (e) {
            return '';
        }
    }

    function matchProvider(path, method) {
        for (var i = 0; i < LLM_ROUTES.length; i++) {
            if (LLM_ROUTES[i].test(path, method)) return LLM_ROUTES[i].provider;
        }
        return null;
    }

    function providerHeaderSubset(provider, allHeaders) {
        var keys = ['X-Gemini-API-Key', 'X-Gemini-Model', 'X-Gemini-API-URL'];
        var out = {};
        keys.forEach(function (k) {
            if (allHeaders[k]) out[k] = allHeaders[k];
        });
        return out;
    }

    if (ORIGINAL_FETCH) {
        window.fetch = function (input, init) {
            try {
                var path = resolvePath(input);
                if (path && path.indexOf('/api/') === 0) {
                    var method = resolveMethod(input, init);
                    var provider = matchProvider(path, method);
                    if (provider) {
                        var extra = providerHeaderSubset(provider, getLLMHeaders());
                        if (Object.keys(extra).length > 0) {
                            var baseHeaders = init && init.headers
                                ? init.headers
                                : (typeof Request !== 'undefined' && input instanceof Request ? input.headers : undefined);
                            var mergedHeaders = new Headers(baseHeaders || {});
                            Object.keys(extra).forEach(function (k) {
                                mergedHeaders.set(k, extra[k]);
                            });

                            if (typeof Request !== 'undefined' && input instanceof Request) {
                                input = new Request(input, { headers: mergedHeaders });
                            } else {
                                init = init ? Object.assign({}, init) : {};
                                init.headers = mergedHeaders;
                            }
                        }
                    }
                }
            } catch (e) {
                console.error('[fds-settings] LLM 헤더 주입 실패:', e);
            }
            return ORIGINAL_FETCH(input, init);
        };
    }

    /* ────────────────────────────────────────────
       4. CSS 주입
       ──────────────────────────────────────────── */
    function injectStyles() {
        if (document.getElementById('fds-settings-styles')) return;

        var css = ''
            + '.settings-btn{background:none;border:1px solid var(--gray-300,#D5D3D0);border-radius:50%;width:36px;height:36px;'
            + 'display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--gray-600,#89898A);margin-left:12px;transition:all 0.15s}'
            + '.settings-btn:hover{border-color:#EE7500;color:#EE7500;background:#FFF7ED}'

            + '.fds-modal-overlay{position:fixed;inset:0;background:rgba(61,59,58,0.45);backdrop-filter:blur(4px);'
            + '-webkit-backdrop-filter:blur(4px);display:none;align-items:center;justify-content:center;z-index:99999;'
            + 'padding:20px;font-family:inherit}'
            + '.fds-modal-overlay.fds-open{display:flex}'

            + '.fds-modal{background:#fff;border-radius:10px;width:520px;max-width:100%;max-height:90vh;overflow-y:auto;'
            + 'box-shadow:0 8px 30px rgba(87,85,83,0.25);display:flex;flex-direction:column;animation:fdsModalIn .15s ease}'
            + '.fds-modal.fds-modal-sm{width:420px}'
            + '@keyframes fdsModalIn{from{opacity:0;transform:translateY(-8px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}'

            + '.fds-modal-header{display:flex;align-items:center;justify-content:space-between;padding:20px 24px;'
            + 'border-bottom:1px solid var(--gray-200,#EEEEEE)}'
            + '.fds-modal-header h2{font-size:17px;font-weight:700;color:var(--hoban-dark,#575553);margin:0}'
            + '.fds-modal-close{background:none;border:none;font-size:22px;line-height:1;color:var(--gray-500,#9E9E9E);'
            + 'cursor:pointer;padding:2px 6px;border-radius:6px;transition:all .15s}'
            + '.fds-modal-close:hover{background:var(--gray-100,#F5F5F5);color:var(--hoban-dark,#575553)}'

            + '.fds-modal-body{padding:20px 24px;display:flex;flex-direction:column;gap:20px}'

            + '.fds-settings-section{border:1px solid var(--gray-200,#EEEEEE);border-radius:10px;padding:16px 18px;'
            + 'display:flex;flex-direction:column;gap:10px;background:var(--gray-50,#FAFAFA)}'
            + '.fds-section-title{display:flex;align-items:center;font-size:14px;font-weight:700;color:var(--hoban-dark,#575553)}'
            + '.fds-section-desc{font-size:12px;color:var(--gray-600,#89898A);margin:-4px 0 2px;line-height:1.5}'

            + '.fds-key-indicator{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;'
            + 'border-radius:50%;background:var(--gray-200,#EEEEEE);color:var(--gray-500,#9E9E9E);font-size:11px;'
            + 'font-weight:700;margin-right:8px;transition:all .15s;flex-shrink:0}'
            + '.fds-key-indicator.fds-active{background:var(--success-bg,#E8F5E9);color:var(--success,#43A047)}'

            + '.fds-field{display:flex;flex-direction:column;gap:5px}'
            + '.fds-field label{font-size:12px;font-weight:600;color:var(--gray-700,#616161)}'
            + '.fds-input-group{position:relative;display:flex;align-items:center}'
            + '.fds-input,.fds-input-group input{width:100%;padding:9px 12px;border:1px solid var(--gray-300,#D5D3D0);'
            + 'border-radius:6px;font-size:13px;font-family:inherit;color:var(--gray-900,#333231);background:#fff;transition:border-color .15s}'
            + '.fds-input:focus,.fds-input-group input:focus{outline:none;border-color:#EE7500}'
            + '.fds-input-group input{padding-right:38px}'
            + '.fds-eye-toggle{position:absolute;right:6px;top:50%;transform:translateY(-50%);background:none;border:none;'
            + 'cursor:pointer;color:var(--gray-500,#9E9E9E);padding:5px;display:flex;align-items:center;justify-content:center;'
            + 'border-radius:4px;transition:color .15s}'
            + '.fds-eye-toggle:hover{color:#EE7500}'

            + '.fds-modal-footer{display:flex;justify-content:flex-end;gap:8px;padding:16px 24px;'
            + 'border-top:1px solid var(--gray-200,#EEEEEE)}'
            + '.fds-btn{padding:9px 18px;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;'
            + 'border:1px solid transparent;font-family:inherit;transition:all .15s}'
            + '.fds-btn-primary{background:#EE7500;color:#fff}'
            + '.fds-btn-primary:hover{background:#D56A00}'
            + '.fds-btn-secondary{background:#fff;color:var(--gray-700,#616161);border-color:var(--gray-300,#D5D3D0)}'
            + '.fds-btn-secondary:hover{border-color:var(--gray-500,#9E9E9E);color:var(--hoban-dark,#575553)}'

            + '.fds-toast{position:fixed;bottom:28px;left:50%;transform:translateX(-50%) translateY(12px);'
            + 'background:var(--hoban-dark,#575553);color:#fff;padding:12px 22px;border-radius:8px;font-size:13px;'
            + 'font-weight:500;box-shadow:0 6px 20px rgba(0,0,0,0.2);z-index:100000;opacity:0;transition:all .25s ease;'
            + 'pointer-events:none;max-width:90vw}'
            + '.fds-toast.fds-show{opacity:1;transform:translateX(-50%) translateY(0)}'

            + '@media (prefers-color-scheme: dark){}'; /* 앱 전체가 라이트 테마 고정이므로 다크모드 오버라이드 없음 */

        var styleEl = document.createElement('style');
        styleEl.id = 'fds-settings-styles';
        styleEl.textContent = css;
        document.head.appendChild(styleEl);
    }

    /* ────────────────────────────────────────────
       5. 아이콘
       ──────────────────────────────────────────── */
    var EYE_ICON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        + 'stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>'
        + '<circle cx="12" cy="12" r="3"/></svg>';
    var EYE_OFF_ICON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        + 'stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.94 10.94 0 0112 20c-7 0-11-8-11-8a20.6 20.6 0 015.06-6.06M9.9 4.24A10.94 10.94 0 0112 4c7 0 11 8 11 8a20.6 20.6 0 01-2.16 3.19M14.12 14.12a3 3 0 11-4.24-4.24"/>'
        + '<line x1="1" y1="1" x2="23" y2="23"/></svg>';
    var GEAR_ICON = '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">'
        + '<circle cx="10" cy="10" r="3"/><path d="M10 1.5v2M10 16.5v2M1.5 10h2M16.5 10h2M3.3 3.3l1.4 1.4M15.3 15.3l1.4 1.4M3.3 16.7l1.4-1.4M15.3 4.7l1.4-1.4"/></svg>';

    /* ────────────────────────────────────────────
       6. 모달 DOM 주입
       ──────────────────────────────────────────── */
    function injectModals() {
        if (document.getElementById('fds-settings-overlay')) return;

        var wrapper = document.createElement('div');
        wrapper.innerHTML =
            '<div id="fds-settings-overlay" class="fds-modal-overlay">'
            + '  <div class="fds-modal" role="dialog" aria-modal="true" aria-label="설정">'
            + '    <div class="fds-modal-header">'
            + '      <h2>설정</h2>'
            + '      <button type="button" class="fds-modal-close" id="fds-settings-close-x" aria-label="닫기">&times;</button>'
            + '    </div>'
            + '    <div class="fds-modal-body">'
            + '      <section class="fds-settings-section">'
            + '        <div class="fds-section-title"><span class="fds-key-indicator" id="fds-indicator-gemini">&#10003;</span>Gemini API</div>'
            + '        <p class="fds-section-desc">OCR 분석, 자연어 룰 생성, 대화형 챗 어시스턴트 등 모든 AI 기능에 사용됩니다.</p>'
            + '        <div class="fds-field">'
            + '          <label for="fds-input-gemini-key">API Key</label>'
            + '          <div class="fds-input-group">'
            + '            <input type="password" id="fds-input-gemini-key" class="fds-input" placeholder="Gemini API Key" autocomplete="off">'
            + '            <button type="button" class="fds-eye-toggle" data-target="fds-input-gemini-key" aria-label="표시/숨김">' + EYE_ICON + '</button>'
            + '          </div>'
            + '        </div>'
            + '        <div class="fds-field">'
            + '          <label for="fds-input-gemini-model">Model</label>'
            + '          <input type="text" id="fds-input-gemini-model" class="fds-input" placeholder="' + DEFAULTS.geminiModel + '">'
            + '        </div>'
            + '        <div class="fds-field">'
            + '          <label for="fds-input-gemini-url">API URL</label>'
            + '          <input type="text" id="fds-input-gemini-url" class="fds-input" placeholder="' + DEFAULTS.geminiUrl + '">'
            + '        </div>'
            + '      </section>'
            + '    </div>'
            + '    <div class="fds-modal-footer">'
            + '      <button type="button" class="fds-btn fds-btn-secondary" id="fds-settings-close">닫기</button>'
            + '      <button type="button" class="fds-btn fds-btn-primary" id="fds-settings-save">저장</button>'
            + '    </div>'
            + '  </div>'
            + '</div>'
            + '<div id="fds-key-popup-overlay" class="fds-modal-overlay">'
            + '  <div class="fds-modal fds-modal-sm" role="dialog" aria-modal="true" aria-label="API 키 필요">'
            + '    <div class="fds-modal-header">'
            + '      <h2>API 키 필요</h2>'
            + '      <button type="button" class="fds-modal-close" id="fds-key-popup-close-x" aria-label="닫기">&times;</button>'
            + '    </div>'
            + '    <div class="fds-modal-body">'
            + '      <p class="fds-section-desc" id="fds-key-popup-desc"></p>'
            + '      <div class="fds-field">'
            + '        <label id="fds-key-popup-label" for="fds-key-popup-input">API Key</label>'
            + '        <div class="fds-input-group">'
            + '          <input type="password" id="fds-key-popup-input" class="fds-input" placeholder="API Key 입력" autocomplete="off">'
            + '          <button type="button" class="fds-eye-toggle" data-target="fds-key-popup-input" aria-label="표시/숨김">' + EYE_ICON + '</button>'
            + '        </div>'
            + '      </div>'
            + '    </div>'
            + '    <div class="fds-modal-footer">'
            + '      <button type="button" class="fds-btn fds-btn-secondary" id="fds-key-popup-cancel">취소</button>'
            + '      <button type="button" class="fds-btn fds-btn-primary" id="fds-key-popup-save">저장 후 계속</button>'
            + '    </div>'
            + '  </div>'
            + '</div>';

        while (wrapper.firstChild) {
            document.body.appendChild(wrapper.firstChild);
        }

        bindStaticEvents();
    }

    /* ────────────────────────────────────────────
       7. 이벤트 바인딩 (정적 - 최초 1회)
       ──────────────────────────────────────────── */
    function bindStaticEvents() {
        // 눈 아이콘 표시/숨김 토글 (이벤트 위임)
        document.addEventListener('click', function (e) {
            var btn = e.target.closest ? e.target.closest('.fds-eye-toggle') : null;
            if (!btn) return;
            var targetId = btn.getAttribute('data-target');
            var input = document.getElementById(targetId);
            if (!input) return;
            var showing = input.type === 'text';
            input.type = showing ? 'password' : 'text';
            btn.innerHTML = showing ? EYE_ICON : EYE_OFF_ICON;
        });

        // 설정 모달 닫기 버튼들
        var closeIds = ['fds-settings-close', 'fds-settings-close-x'];
        closeIds.forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.addEventListener('click', closeSettings);
        });

        // 설정 모달 저장 버튼
        var saveBtn = document.getElementById('fds-settings-save');
        if (saveBtn) saveBtn.addEventListener('click', saveSettings);

        // 오버레이 바깥 클릭 시 닫기
        var settingsOverlay = document.getElementById('fds-settings-overlay');
        if (settingsOverlay) {
            settingsOverlay.addEventListener('click', function (e) {
                if (e.target === settingsOverlay) closeSettings();
            });
        }

        var popupOverlay = document.getElementById('fds-key-popup-overlay');
        if (popupOverlay) {
            popupOverlay.addEventListener('click', function (e) {
                if (e.target === popupOverlay) {
                    var cancelBtn = document.getElementById('fds-key-popup-cancel');
                    if (cancelBtn) cancelBtn.click();
                }
            });
        }

        // ESC 키로 열려 있는 모달 닫기
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape') return;
            var settingsOpen = settingsOverlay && settingsOverlay.classList.contains('fds-open');
            var popupOpen = popupOverlay && popupOverlay.classList.contains('fds-open');
            if (popupOpen) {
                var cancelBtn = document.getElementById('fds-key-popup-cancel');
                if (cancelBtn) cancelBtn.click();
            } else if (settingsOpen) {
                closeSettings();
            }
        });
    }

    /* ────────────────────────────────────────────
       8. 설정 모달 열기/닫기/저장
       ──────────────────────────────────────────── */
    function updateIndicators() {
        var geminiActive = !!getStored(STORAGE_KEYS.geminiKey, '');
        var gEl = document.getElementById('fds-indicator-gemini');
        if (gEl) {
            gEl.classList.toggle('fds-active', geminiActive);
            gEl.title = geminiActive ? 'API 키 저장됨' : 'API 키 미설정';
        }
    }

    function showToast(message) {
        var existing = document.getElementById('fds-toast');
        if (existing) existing.parentNode.removeChild(existing);

        var toast = document.createElement('div');
        toast.id = 'fds-toast';
        toast.className = 'fds-toast';
        toast.textContent = message;
        document.body.appendChild(toast);

        window.requestAnimationFrame(function () {
            toast.classList.add('fds-show');
        });
        window.setTimeout(function () {
            toast.classList.remove('fds-show');
            window.setTimeout(function () {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, 300);
        }, 2200);
    }

    function openSettings() {
        injectStyles();
        injectModals();

        var geminiKeyInput = document.getElementById('fds-input-gemini-key');
        var geminiModelInput = document.getElementById('fds-input-gemini-model');
        var geminiUrlInput = document.getElementById('fds-input-gemini-url');

        if (geminiKeyInput) geminiKeyInput.value = getStored(STORAGE_KEYS.geminiKey, '');
        if (geminiModelInput) geminiModelInput.value = getStored(STORAGE_KEYS.geminiModel, DEFAULTS.geminiModel);
        if (geminiUrlInput) geminiUrlInput.value = getStored(STORAGE_KEYS.geminiUrl, DEFAULTS.geminiUrl);

        if (geminiKeyInput) geminiKeyInput.type = 'password';
        document.querySelectorAll('#fds-settings-overlay .fds-eye-toggle').forEach(function (btn) {
            btn.innerHTML = EYE_ICON;
        });

        updateIndicators();

        var overlay = document.getElementById('fds-settings-overlay');
        if (overlay) overlay.classList.add('fds-open');
    }
    window.openSettings = openSettings;

    function closeSettings() {
        var overlay = document.getElementById('fds-settings-overlay');
        if (overlay) overlay.classList.remove('fds-open');
    }
    window.closeSettings = closeSettings;

    function saveSettings() {
        var geminiKey = ((document.getElementById('fds-input-gemini-key') || {}).value || '').trim();
        var geminiModel = ((document.getElementById('fds-input-gemini-model') || {}).value || '').trim();
        var geminiUrl = ((document.getElementById('fds-input-gemini-url') || {}).value || '').trim();

        setStored(STORAGE_KEYS.geminiKey, geminiKey);
        setStored(STORAGE_KEYS.geminiModel, geminiModel || DEFAULTS.geminiModel);
        setStored(STORAGE_KEYS.geminiUrl, geminiUrl || DEFAULTS.geminiUrl);

        updateIndicators();
        showToast('설정이 저장되었습니다.');
    }

    /* ────────────────────────────────────────────
       9. 포커스 팝업: requireGeminiKey()
       ──────────────────────────────────────────── */
    function requireKey(provider) {
        return new Promise(function (resolve, reject) {
            var existing = getStored(STORAGE_KEYS.geminiKey, '');
            if (existing) {
                resolve(existing);
                return;
            }
            openKeyPopup(provider, resolve, reject);
        });
    }
    window.requireGeminiKey = function () { return requireKey('gemini'); };

    function openKeyPopup(provider, resolve, reject) {
        injectStyles();
        injectModals();

        var overlay = document.getElementById('fds-key-popup-overlay');
        var desc = document.getElementById('fds-key-popup-desc');
        var label = document.getElementById('fds-key-popup-label');
        var input = document.getElementById('fds-key-popup-input');
        var saveBtn = document.getElementById('fds-key-popup-save');
        var cancelBtn = document.getElementById('fds-key-popup-cancel');
        var closeBtn = document.getElementById('fds-key-popup-close-x');
        var eyeBtn = overlay ? overlay.querySelector('.fds-eye-toggle') : null;

        if (!overlay || !input || !saveBtn || !cancelBtn) {
            reject(new Error('설정 팝업을 표시할 수 없습니다.'));
            return;
        }

        desc.textContent = 'AI 기능(OCR, 챗 어시스턴트, 자연어 룰 생성)을 사용하려면 Gemini API Key가 필요합니다.';
        label.textContent = 'Gemini API Key';
        input.value = '';
        input.placeholder = 'Gemini API Key';
        input.type = 'password';
        if (eyeBtn) eyeBtn.innerHTML = EYE_ICON;

        var settled = false;

        function cleanup() {
            overlay.classList.remove('fds-open');
            saveBtn.removeEventListener('click', onSave);
            cancelBtn.removeEventListener('click', onCancel);
            if (closeBtn) closeBtn.removeEventListener('click', onCancel);
            input.removeEventListener('keydown', onKeydown);
        }

        function onSave() {
            if (settled) return;
            var val = (input.value || '').trim();
            if (!val) {
                input.focus();
                return;
            }
            setStored(STORAGE_KEYS.geminiKey, val);
            updateIndicators();
            settled = true;
            cleanup();
            resolve(val);
        }

        function onCancel() {
            if (settled) return;
            settled = true;
            cleanup();
            reject(new Error('API 키 입력이 취소되었습니다.'));
        }

        function onKeydown(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                onSave();
            }
        }

        saveBtn.addEventListener('click', onSave);
        cancelBtn.addEventListener('click', onCancel);
        if (closeBtn) closeBtn.addEventListener('click', onCancel);
        input.addEventListener('keydown', onKeydown);

        overlay.classList.add('fds-open');
        window.setTimeout(function () { input.focus(); }, 50);
    }

    /* ────────────────────────────────────────────
       10. 네비게이션 바에 설정 버튼 추가
       ──────────────────────────────────────────── */
    function injectSettingsButton() {
        var nav = document.querySelector('.navbar nav');
        if (!nav || nav.querySelector('.settings-btn')) return;

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'settings-btn';
        btn.title = '설정';
        btn.setAttribute('onclick', 'openSettings()');
        btn.innerHTML = GEAR_ICON;
        nav.appendChild(btn);
    }

    /* ────────────────────────────────────────────
       11. 초기화
       ──────────────────────────────────────────── */
    function init() {
        injectStyles();
        injectModals();
        injectSettingsButton();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
