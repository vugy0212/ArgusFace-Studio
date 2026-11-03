/* =========================================================================
   ArgusFace Studio — Biometric Mobile Web App Logic
   Supports: Live Camera, 1:N Search, 1:1 Compare, Enrollment, Admin & PIN
   ========================================================================= */

// Base API configuration (points to relative origin or configured host)
const API_BASE = window.location.origin;

// State management
let state = {
    cameraStream: null,
    facingMode: 'user', // 'user' or 'environment'
    capturedBlob: null,
    compareSlot1Blob: null,
    compareSlot2Blob: null,
    enrollBlob: null,
    selectedRole: 'standard',
    enteredPin: '',
    correctPin: '121977',
    isUnlocked: false
};

// Telegram WebApp SDK setup
const tg = window.Telegram?.WebApp;
if (tg) {
    tg.ready();
    tg.expand();
    if (tg.setHeaderColor) tg.setHeaderColor('#060911');
    if (tg.setBackgroundColor) tg.setBackgroundColor('#060911');
}

function triggerHaptic(type = 'light') {
    try {
        if (tg?.HapticFeedback) {
            if (type === 'light' || type === 'medium' || type === 'heavy') {
                tg.HapticFeedback.impactOccurred(type);
            } else if (type === 'success' || type === 'error' || type === 'warning') {
                tg.HapticFeedback.notificationOccurred(type);
            }
        }
    } catch (_) {}
}

function showToast(message, duration = 2500) {
    const toast = document.getElementById('toastNotification');
    if (!toast) return;
    toast.textContent = message;
    toast.style.display = 'block';
    setTimeout(() => {
        toast.style.display = 'none';
    }, duration);
}

// =========================================================================
// 1. PIN LOCK & AUTHENTICATION
// =========================================================================

function initPinLock() {
    const urlParams = new URLSearchParams(window.location.search);
    const hasUrlAuth = urlParams.get('auth') === '1' || urlParams.has('chat_id');
    const isTelegramWebApp = Boolean(
        (window.Telegram?.WebApp?.initData && window.Telegram.WebApp.initData.length > 0) ||
        window.Telegram?.WebApp?.initDataUnsafe?.user
    );
    const savedLocalAuth = localStorage.getItem('argusface_session_auth') === 'true';
    const savedSessionAuth = sessionStorage.getItem('argusface_session_auth') === 'true';

    // If opened via Telegram bot (which already required PIN unlock) or previously authenticated
    if (hasUrlAuth || isTelegramWebApp || savedLocalAuth || savedSessionAuth) {
        state.isUnlocked = true;
        localStorage.setItem('argusface_session_auth', 'true');
        sessionStorage.setItem('argusface_session_auth', 'true');
        const modal = document.getElementById('pinLockModal');
        if (modal) modal.style.display = 'none';
        loadSystemStatus();
        return;
    }

    // Fetch live PIN from server
    fetch(`${API_BASE}/api/v1/bot/users`)
        .then(r => r.json())
        .then(data => {
            if (data && data.pin) {
                state.correctPin = String(data.pin).trim();
            }
        })
        .catch(() => {});

    // Show lock modal only if direct unauthorized access outside Telegram
    document.getElementById('pinLockModal').style.display = 'flex';

    // Keypad listeners
    document.querySelectorAll('.key-btn[data-key]').forEach(btn => {
        btn.addEventListener('click', () => {
            triggerHaptic('light');
            if (state.enteredPin.length < 6) {
                state.enteredPin += btn.dataset.key;
                updatePinDots();
                if (state.enteredPin.length === 6) {
                    verifyPin();
                }
            }
        });
    });

    document.getElementById('btnPinBackspace')?.addEventListener('click', () => {
        triggerHaptic('light');
        if (state.enteredPin.length > 0) {
            state.enteredPin = state.enteredPin.slice(0, -1);
            updatePinDots();
        }
    });

    document.getElementById('btnPinClear')?.addEventListener('click', () => {
        triggerHaptic('medium');
        state.enteredPin = '';
        updatePinDots();
    });
}

function updatePinDots() {
    for (let i = 1; i <= 6; i++) {
        const dot = document.getElementById(`dot${i}`);
        if (dot) {
            if (i <= state.enteredPin.length) {
                dot.classList.add('filled');
            } else {
                dot.classList.remove('filled');
            }
        }
    }
}

function verifyPin() {
    if (state.enteredPin === state.correctPin) {
        triggerHaptic('success');
        state.isUnlocked = true;
        localStorage.setItem('argusface_session_auth', 'true');
        sessionStorage.setItem('argusface_session_auth', 'true');
        showToast('🔓 Pristup odobren!');
        setTimeout(() => {
            document.getElementById('pinLockModal').style.display = 'none';
            loadSystemStatus();
        }, 300);
    } else {
        triggerHaptic('error');
        const dots = document.querySelector('.pin-dots');
        dots.classList.add('shake');
        showToast('❌ Pogrešan PIN');
        setTimeout(() => {
            dots.classList.remove('shake');
            state.enteredPin = '';
            updatePinDots();
        }, 500);
    }
}

function lockSession() {
    triggerHaptic('heavy');
    state.isUnlocked = false;
    localStorage.removeItem('argusface_session_auth');
    sessionStorage.removeItem('argusface_session_auth');
    state.enteredPin = '';
    updatePinDots();
    document.getElementById('pinLockModal').style.display = 'flex';
}

// =========================================================================
// 2. TAB 1: PHOTO SCAN & BIOMETRIC RECOGNITION (1:N)
// =========================================================================

function handleScanFile(file) {
    if (!file) return;
    state.capturedBlob = file;

    const preview = document.getElementById('scanPreviewImg');
    const previewWrapper = document.getElementById('scanPreviewWrapper');
    const placeholder = document.getElementById('scanPlaceholder');
    const btnExecute = document.getElementById('btnExecuteSearch');
    const resultCard = document.getElementById('scanResultCard');

    if (resultCard) resultCard.style.display = 'none';

    preview.src = URL.createObjectURL(file);
    previewWrapper.style.display = 'block';
    placeholder.style.display = 'none';
    btnExecute.disabled = false;
    btnExecute.classList.add('glow');

    triggerHaptic('medium');
    showToast('📸 Fotografija učitana. Kliknite "Pretraži u bazi".');
}

function clearScanPhoto() {
    state.capturedBlob = null;
    const preview = document.getElementById('scanPreviewImg');
    const previewWrapper = document.getElementById('scanPreviewWrapper');
    const placeholder = document.getElementById('scanPlaceholder');
    const btnExecute = document.getElementById('btnExecuteSearch');
    const fileInput = document.getElementById('fileInputScan');
    const fileCam = document.getElementById('fileInputScanCamera');
    const fileGal = document.getElementById('fileInputScanGallery');
    const resultCard = document.getElementById('scanResultCard');

    if (fileInput) fileInput.value = '';
    if (fileCam) fileCam.value = '';
    if (fileGal) fileGal.value = '';
    preview.src = '';
    previewWrapper.style.display = 'none';
    placeholder.style.display = 'flex';
    btnExecute.disabled = true;
    btnExecute.classList.remove('glow');
    if (resultCard) resultCard.style.display = 'none';

    triggerHaptic('light');
}

async function executeSearch() {
    if (!state.capturedBlob) {
        showToast('⚠️ Prvo odaberite ili snimite fotografiju lica.');
        return;
    }

    triggerHaptic('heavy');
    const btnExecute = document.getElementById('btnExecuteSearch');
    const laser = document.getElementById('scanLaser');

    btnExecute.disabled = true;
    btnExecute.innerHTML = `
        <span class="spinner-small"></span>
        <span>Analiziram biometriju...</span>
    `;

    if (laser) laser.style.animationDuration = '0.7s';

    const formData = new FormData();
    formData.append('image', state.capturedBlob, 'scan.jpg');
    formData.append('check_spoofing', 'true');

    try {
        const resp = await fetch(`${API_BASE}/api/v1/search`, {
            method: 'POST',
            body: formData
        });

        if (laser) laser.style.animationDuration = '3s';

        if (!resp.ok) {
            throw new Error(`HTTP ${resp.status}`);
        }

        const data = await resp.json();
        renderScanResult(data, state.capturedBlob);
    } catch (err) {
        console.error('Scan error:', err);
        showToast('❌ Greška pri analizi: ' + err.message);
        if (laser) laser.style.animationDuration = '3s';
    } finally {
        btnExecute.disabled = false;
        btnExecute.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <circle cx="11" cy="11" r="8"/>
                <path d="m21 21-4.35-4.35"/>
            </svg>
            <span>Pretraži u bazi (1:N)</span>
        `;
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderScanResult(data, queryBlob) {
    const container = document.getElementById('scanResultCard');
    const hudStatus = document.getElementById('hudStatus');

    if (!container) return;

    // Total detected faces count check
    const totalFaces = (typeof data.faces_detected !== 'undefined') ? data.faces_detected : (data.total_faces ?? 0);
    const results = data.results || data.matches || [];

    if (totalFaces === 0 || results.length === 0) {
        triggerHaptic('warning');
        const queryImgUrl = queryBlob ? URL.createObjectURL(queryBlob) : '';
        container.innerHTML = `
            <div class="result-card">
                <div class="result-header">
                    <span class="badge unknown">NEMA LICA</span>
                    <span class="res-time">Analiza završena</span>
                </div>
                <div class="result-body">
                    <div class="result-photos" style="justify-content: center;">
                        <div class="photo-box" style="max-width: 160px;">
                            <span class="photo-tag">Učitana slika</span>
                            <img src="${queryImgUrl}" alt="Učitana slika">
                        </div>
                    </div>
                    <div class="result-details" style="text-align: center;">
                        <h3>Nije detektirano lice</h3>
                        <p class="res-notes" style="margin-top: 8px;">
                            Na fotografiji nije pronađeno niti jedno lice. Osigurajte dobro osvjetljenje, čist kadar i pogled usmjeren prema kameri.
                        </p>
                    </div>
                </div>
            </div>
        `;
        if (hudStatus) hudStatus.textContent = 'NEMA LICA';
        container.style.display = 'flex';
        container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        return;
    }

    const matchedCount = results.filter(r => r.matched).length;
    const unknownCount = results.length - matchedCount;

    if (matchedCount > 0) {
        triggerHaptic('success');
        if (hudStatus) {
            hudStatus.textContent = results.length > 1
                ? `PREPOZNATO: ${matchedCount}/${results.length} LICA`
                : `IDENTIFICIRANO: ${(results[0].person_name || 'OSOBA').toUpperCase()} (${results[0].similarity_pct || Math.round((results[0].similarity || 0) * 100)}%)`;
        }
    } else {
        triggerHaptic('warning');
        if (hudStatus) {
            hudStatus.textContent = results.length > 1
                ? `DETEKTIRANO ${results.length} NEPOZNATIH LICA`
                : `NEPOZNATA OSOBA (${results[0].similarity_pct || Math.round((results[0].similarity || 0) * 100)}%)`;
        }
    }

    let html = '';

    // 1. Summary Bar (especially clear for multiple faces)
    html += `
        <div class="results-summary-card">
            <div class="summary-stat-group">
                <span class="stat-item total">👥 Pronađeno lica: <strong>${results.length}</strong></span>
                <span class="stat-item matched">🟢 Prepoznato: <strong>${matchedCount}</strong></span>
                ${unknownCount > 0 ? `<span class="stat-item unknown">⚪ Nepoznato: <strong>${unknownCount}</strong></span>` : ''}
            </div>
            ${data.annotated_image_base64 ? `
                <button type="button" class="annotated-toggle-btn" id="btnToggleAnnotated" onclick="toggleAnnotatedPreview()">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                        <circle cx="8.5" cy="8.5" r="1.5"/>
                        <polyline points="21 15 16 10 5 21"/>
                    </svg>
                    <span id="txtToggleAnnotated">Prikaži označena lica</span>
                </button>
            ` : ''}
        </div>
    `;

    // 2. Full image with annotations (toggleable)
    if (data.annotated_image_base64) {
        html += `
            <div class="annotated-image-box" id="annotatedImageBox" style="display: none;">
                <img src="data:image/jpeg;base64,${data.annotated_image_base64}" alt="Označena lica u kadru">
            </div>
        `;
    }

    window._lastSearchResults = results;

    // 3. Render card for EACH detected face
    results.forEach((f, idx) => {
        const isMatched = Boolean(f.matched);
        const status = f.status || '';
        const isPossible = (!isMatched && status === 'Moguće poklapanje' && f.person_name && f.person_name !== 'Nepoznat' && f.person_name !== 'Nepoznato');

        let name = f.person_name || f.name || 'Nepoznata osoba';
        if (!isMatched && !isPossible) {
            name = 'Nepoznata osoba';
        }
        const role = (f.role || 'standard').toLowerCase();
        const simPct = (typeof f.similarity_pct !== 'undefined') ? f.similarity_pct : Math.round((f.similarity || 0) * 100);

        let badgeClass = 'badge';
        let badgeText = 'PREPOZNATO';
        let fillBg = 'linear-gradient(90deg, var(--accent-cyan), var(--accent-green))';
        let rolePillClass = `role-pill ${role}`;
        let rolePillText = role.toUpperCase();

        if (isMatched) {
            if (role === 'blacklist') {
                badgeClass = 'badge blacklist';
                badgeText = 'CRNA LISTA';
                fillBg = 'var(--accent-red)';
            } else if (role === 'vip') {
                badgeClass = 'badge vip';
                badgeText = 'VIP GOST';
                fillBg = 'var(--accent-amber)';
            } else {
                badgeClass = 'badge';
                badgeText = 'PREPOZNATO';
                fillBg = 'linear-gradient(90deg, var(--accent-cyan), var(--accent-green))';
            }
        } else if (isPossible) {
            badgeClass = 'badge warning';
            badgeText = 'MOGUĆE';
            fillBg = 'linear-gradient(90deg, #f59e0b, #eab308)';
            rolePillClass = `role-pill ${role}`;
            rolePillText = `${role.toUpperCase()}?`;
        } else {
            badgeClass = 'badge unknown';
            badgeText = 'NEPOZNATO';
            fillBg = 'rgba(255, 255, 255, 0.2)';
            rolePillClass = 'role-pill unknown';
            rolePillText = 'NIJE U BAZI';
        }

        const queryCropSrc = f.query_crop_base64
            ? `data:image/jpeg;base64,${f.query_crop_base64}`
            : (queryBlob ? URL.createObjectURL(queryBlob) : '');

        const dbCropSrc = f.sample_image_base64
            ? `data:image/jpeg;base64,${f.sample_image_base64}`
            : (f.sample_image_url ? `${API_BASE}${f.sample_image_url}` : null);

        const meterWidth = Math.min(100, Math.max(5, simPct));

        // Format demographics & info
        const chips = [];
        if (f.age || f.gender) {
            const ageStr = f.age ? `~${f.age} god` : '';
            const genStr = f.gender || '';
            const bio = [ageStr, genStr].filter(Boolean).join(', ');
            chips.push(`📐 Dob/Spol: ${bio}`);
        }
        if (typeof f.is_real !== 'undefined') {
            const liveConfPct = Math.round(Number(f.liveness_conf || 1.0) * 100);
            chips.push(f.is_real ? `🛡️ Autentično lice (${liveConfPct}%)` : `⚠️ Mogući ekran/slika (${liveConfPct}%)`);
        }
        if (isMatched && f.person_id) {
            chips.push(`🏷️ ID #${f.person_id} • Uzoraka: ${f.sample_count || 1}`);
        } else if (isPossible) {
            chips.push(`⚠️ Sličnost ispod sigurnosnog praga`);
        }

        const simSubtext = isMatched
            ? `${simPct}% sličnost`
            : (isPossible ? `Moguće poklapanje: ${simPct}%` : `Maks. sličnost: ${simPct}%`);

        html += `
            <div class="result-card ${(isMatched || isPossible) ? 'clickable-result-card' : ''}" data-face-idx="${idx}" ${(isMatched || isPossible) ? `onclick="if (!event.target.closest('button')) openPersonModalFromScan(${idx})"` : ''}>
                <div class="result-header">
                    <div class="face-title-group">
                        <span class="face-index-chip">Lice #${idx + 1}</span>
                        <span class="${badgeClass}">${badgeText}</span>
                    </div>
                    <span class="res-time">${isMatched ? 'Usklađeno' : (isPossible ? 'Ispod praga' : 'Nema poklapanja')}</span>
                </div>

                <div class="result-body">
                    <div class="result-photos">
                        <div class="photo-box">
                            <span class="photo-tag">Upitno lice</span>
                            <img src="${queryCropSrc}" alt="Lice #${idx + 1}">
                        </div>
                        <div class="photo-divider">
                            <div class="divider-icon">${isMatched ? '⚡' : (isPossible ? '≈' : '—')}</div>
                        </div>
                        <div class="photo-box ${dbCropSrc ? '' : 'photo-box-empty'}">
                            <span class="photo-tag">Baza podataka</span>
                            ${dbCropSrc ? `
                                <img src="${dbCropSrc}" alt="Referenca baze">
                            ` : `
                                <div class="empty-db-photo">
                                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="26" height="26">
                                        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                                        <circle cx="12" cy="7" r="4"/>
                                        <line x1="18" y1="8" x2="23" y2="13"/>
                                        <line x1="23" y1="8" x2="18" y2="13"/>
                                    </svg>
                                    <span>Nije u bazi</span>
                                </div>
                            `}
                        </div>
                    </div>

                    <div class="result-details">
                        <h3 class="${(isMatched || isPossible) ? 'clickable-person-title' : ''}" ${(isMatched || isPossible) ? `onclick="openPersonModalFromScan(${idx})"` : ''} title="Dodirnite za detalje i izmjenu podataka">${escapeHtml(name)} ${(isMatched || isPossible) ? '<span class="edit-hint-icon">✏️</span>' : ''}</h3>
                        <div class="details-row">
                            <span class="${rolePillClass}">${rolePillText}</span>
                            <span class="similarity-text">${simSubtext}</span>
                        </div>

                        <div class="meter-bar">
                            <div class="meter-fill" style="width: ${meterWidth}%; background: ${fillBg};"></div>
                        </div>

                        ${chips.length > 0 ? `
                            <div class="face-attributes-grid">
                                ${chips.map(c => `<span class="attr-chip">${escapeHtml(c)}</span>`).join('')}
                            </div>
                        ` : ''}

                        <!-- Quick Action Buttons for 1-Tap workflow -->
                        <div class="result-card-actions">
                            ${(isMatched || isPossible) ? `
                                <button type="button" class="action-pill-btn edit-btn" onclick="openPersonModalFromScan(${idx})">
                                    <span>✏️ Uredi osobu</span>
                                </button>
                                <button type="button" class="action-pill-btn primary" onclick="quickEnrollFor('${escapeHtml(name)}', '${role}')">
                                    <span>📸 Dodaj sliku (${escapeHtml(name.split(' ')[0])})</span>
                                </button>
                            ` : `
                                <button type="button" class="action-pill-btn primary" onclick="quickEnrollNewFace(${idx})">
                                    <span>➕ Registriraj ovo lice</span>
                                </button>
                            `}
                            <button type="button" class="action-pill-btn secondary" onclick="resetScanAndRetake()">
                                <span>🔄 Novo skeniranje</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
    container.style.display = 'flex';
    container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

window.openPersonModalFromScan = function(faceIdx) {
    if (window._lastSearchResults && window._lastSearchResults[faceIdx]) {
        const item = window._lastSearchResults[faceIdx];
        if (item.person_id) {
            openPersonModal(item.person_id);
        } else if (item.person_name || item.name) {
            openPersonModal(item.person_name || item.name);
        }
    }
};

function toggleAnnotatedPreview() {
    const box = document.getElementById('annotatedImageBox');
    const txt = document.getElementById('txtToggleAnnotated');
    if (!box) return;
    if (box.style.display === 'none' || !box.style.display) {
        box.style.display = 'block';
        if (txt) txt.textContent = 'Sakrij označena lica';
    } else {
        box.style.display = 'none';
        if (txt) txt.textContent = 'Prikaži označena lica';
    }
}

// =========================================================================
// 4. TAB 2: 1:1 FACE COMPARISON
// =========================================================================

function triggerCompareInput(slotNum) {
    triggerHaptic('light');
    document.getElementById(`fileSlot${slotNum}`)?.click();
}

function triggerCompareCamera(slotNum) {
    triggerHaptic('light');
    const camInput = document.getElementById(`fileSlot${slotNum}Camera`);
    if (camInput) {
        camInput.value = '';
        camInput.click();
    }
}

function handleCompareFile(slotNum, file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
        const img = document.getElementById(`imgSlot${slotNum}`);
        const preview = document.getElementById(`previewSlot${slotNum}`);
        img.src = e.target.result;
        img.style.display = 'block';
        if (preview) preview.style.display = 'none';

        if (slotNum === 1) state.compareSlot1Blob = file;
        if (slotNum === 2) state.compareSlot2Blob = file;
    };
    reader.readAsDataURL(file);
}

async function runComparison() {
    triggerHaptic('heavy');
    if (!state.compareSlot1Blob || !state.compareSlot2Blob) {
        showToast('⚠️ Odaberite obje fotografije za usporedbu.');
        return;
    }

    const btn = document.getElementById('btnRunCompare');
    btn.disabled = true;
    btn.querySelector('span').textContent = 'USPOREĐUJEM BIOMETRIJU...';

    const formData = new FormData();
    formData.append('image1', state.compareSlot1Blob, 'slot1.jpg');
    formData.append('image2', state.compareSlot2Blob, 'slot2.jpg');

    try {
        const resp = await fetch(`${API_BASE}/api/v1/compare`, {
            method: 'POST',
            body: formData
        });

        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        renderCompareResult(data);
    } catch (err) {
        showToast('❌ Greška pri usporedbi: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.querySelector('span').textContent = 'USPOREDI BIOMETRIJU';
    }
}

function renderCompareResult(data) {
    const card = document.getElementById('compareResultCard');
    const icon = document.getElementById('compareVerdictIcon');
    const title = document.getElementById('compareVerdictTitle');
    const desc = document.getElementById('compareVerdictDesc');
    const score = document.getElementById('compareScore');
    const fill = document.getElementById('compareMeterFill');

    const pct = Math.round((data.similarity || 0) * 100);
    score.textContent = `${pct}%`;
    fill.style.width = `${pct}%`;

    const isMatch = Boolean(data.same_person || data.is_match);
    if (isMatch) {
        triggerHaptic('success');
        icon.textContent = '✅';
        title.textContent = 'ISTA OSOBA (MATCH)';
        title.style.color = 'var(--accent-green)';
        desc.textContent = `Biometrijski vektori potvrđuju identitet (prag: ${Math.round(data.threshold * 100)}%)`;
    } else {
        triggerHaptic('error');
        icon.textContent = '❌';
        title.textContent = 'RAZLIČITE OSOBE (NO MATCH)';
        title.style.color = 'var(--accent-red)';
        desc.textContent = `Vektori se ne podudaraju (sličnost je ispod praga od ${Math.round(data.threshold * 100)}%)`;
    }

    card.style.display = 'block';
    card.scrollIntoView({ behavior: 'smooth' });
}

// =========================================================================
// 5. TAB 3: ENROLLMENT
// =========================================================================

function handleEnrollFile(file) {
    if (!file) return;
    state.enrollBlob = file;
    const reader = new FileReader();
    reader.onload = (e) => {
        const img = document.getElementById('enrollPreviewImg');
        const ph = document.getElementById('enrollPlaceholder');
        img.src = e.target.result;
        img.style.display = 'block';
        if (ph) ph.style.display = 'none';
    };
    reader.readAsDataURL(file);
}

async function submitEnrollment() {
    triggerHaptic('heavy');
    const nameInput = document.getElementById('enrollName');
    const notesInput = document.getElementById('enrollNotes');
    const name = nameInput.value.trim();
    const notes = notesInput.value.trim();

    if (!state.enrollBlob) {
        showToast('⚠️ Odaberite fotografiju lica.');
        return;
    }
    if (!name) {
        showToast('⚠️ Upišite ime i prezime osobe.');
        nameInput.focus();
        return;
    }

    const btn = document.getElementById('btnSubmitEnroll');
    btn.disabled = true;
    btn.querySelector('span').textContent = 'SPREMAM U BAZU...';

    const formData = new FormData();
    formData.append('image', state.enrollBlob, 'enroll.jpg');
    formData.append('name', name);
    formData.append('role', state.selectedRole);
    formData.append('notes', notes);

    try {
        const resp = await fetch(`${API_BASE}/api/v1/persons/enroll`, {
            method: 'POST',
            body: formData
        });

        if (!resp.ok) {
            const errJson = await resp.json().catch(() => ({}));
            throw new Error(errJson.detail || `HTTP ${resp.status}`);
        }

        const data = await resp.json();
        triggerHaptic('success');
        showToast(`✅ ${name} uspješno upisan/a u bazu! (ID #${data.person_id})`);

        // Reset form
        nameInput.value = '';
        notesInput.value = '';
        state.enrollBlob = null;
        document.getElementById('enrollPreviewImg').style.display = 'none';
        document.getElementById('enrollPlaceholder').style.display = 'flex';

        // Refresh stats
        loadSystemStatus();
    } catch (err) {
        triggerHaptic('error');
        showToast('❌ Greška: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.querySelector('span').textContent = 'SPREMI OSOBU U BAZU';
    }
}

// =========================================================================
// 6. TAB 4: SYSTEM STATUS & AUTHORIZED USERS
// =========================================================================

async function loadSystemStatus() {
    try {
        const sResp = await fetch(`${API_BASE}/api/v1/status`);
        if (sResp.ok) {
            const s = await sResp.json();
            document.getElementById('statPersons').textContent = s.total_persons ?? 0;
            document.getElementById('statSamples').textContent = s.total_samples ?? 0;
            document.getElementById('statIndex').textContent = s.has_faiss ? 'FAISS HNSW' : 'NumPy BLAS';
            document.getElementById('statSpoofing').textContent = s.anti_spoofing ? 'Aktivno' : 'Neaktivno';
            document.getElementById('headerEngineBadge').textContent = 'AI ONLINE';
            document.getElementById('headerEngineBadge').style.color = 'var(--accent-green)';
        }
    } catch (_) {
        document.getElementById('headerEngineBadge').textContent = 'AI OFFLINE';
        document.getElementById('headerEngineBadge').style.color = 'var(--accent-red)';
    }

    // Load Bot Config (PIN and Users)
    try {
        const uResp = await fetch(`${API_BASE}/api/v1/bot/users`);
        if (uResp.ok) {
            const cfg = await uResp.json();
            if (cfg.pin) {
                state.correctPin = String(cfg.pin).trim();
            }

            const users = cfg.allowed_users || [];
            document.getElementById('userCountBadge').textContent = users.length;
            const listEl = document.getElementById('authorizedUserList');
            if (listEl) {
                if (users.length === 0) {
                    listEl.innerHTML = '<div style="font-size:0.8rem;color:var(--text-muted);padding:8px;">Nema ovlaštenih korisnika.</div>';
                } else {
                    listEl.innerHTML = users.map(u => `
                        <div class="user-item">
                            <div>
                                <div class="user-item-name">${escapeHtml(u.name || 'Nepoznato')}</div>
                                <div class="user-item-id">Chat ID: ${u.chat_id}</div>
                            </div>
                            <span class="user-item-badge ${u.role === 'admin' ? 'admin' : 'user'}">
                                ${u.role === 'admin' ? 'ADMIN' : 'KORISNIK'}
                            </span>
                        </div>
                    `).join('');
                }
            }
        }
    } catch (_) {}

    // Load Persons Database Directory
    loadPersonsDirectory(currentPersonsFilter.query, currentPersonsFilter.role);
}

let currentPersonsFilter = { query: '', role: 'all' };
let searchDebounceTimer = null;

async function loadPersonsDirectory(query = '', role = 'all') {
    const listEl = document.getElementById('personsDirectoryList');
    const badgeEl = document.getElementById('personsCountBadge');
    if (!listEl) return;

    listEl.innerHTML = '<div class="loading-spinner">Pretražujem bazu...</div>';

    try {
        let url = `${API_BASE}/api/v1/persons?limit=100`;
        if (query && query.trim()) {
            url += `&query=${encodeURIComponent(query.trim())}`;
        }
        if (role && role !== 'all') {
            url += `&role=${encodeURIComponent(role)}`;
        }

        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        const persons = data.persons || [];
        const total = data.total ?? persons.length;

        if (badgeEl) badgeEl.textContent = total;

        // Cache loaded directory persons for instantaneous modal opening
        if (!window._directoryPersons) window._directoryPersons = {};
        persons.forEach(p => {
            window._directoryPersons[p.id] = p;
        });

        if (persons.length === 0) {
            const hasQuery = Boolean(query && query.trim());
            listEl.innerHTML = `
                <div class="empty-persons-box">
                    <p>${hasQuery ? `❌ Nema pronađenih osoba za pojam "<strong>${escapeHtml(query)}</strong>".` : 'Baza registriranih osoba je prazna.'}</p>
                    <button type="button" class="small-btn" onclick="goToEnrollTab()">➕ Registriraj novo lice</button>
                </div>
            `;
            return;
        }

        listEl.innerHTML = persons.map(p => {
            const r = (p.role || 'standard').toLowerCase();
            let roleBadgeClass = 'standard';
            let roleLabel = 'STANDARD';
            if (r === 'blacklist') {
                roleBadgeClass = 'blacklist';
                roleLabel = 'CRNA LISTA';
            } else if (r === 'vip') {
                roleBadgeClass = 'vip';
                roleLabel = 'VIP';
            }

            const avatarSrc = p.thumbnail_base64
                ? `data:image/jpeg;base64,${p.thumbnail_base64}`
                : '';

            return `
                <div class="person-item-card" data-person-id="${p.id}" role="button" tabindex="0" onclick="openPersonModal(${p.id})">
                    <div class="person-avatar-box">
                        ${avatarSrc ? `<img src="${avatarSrc}" alt="${escapeHtml(p.name)}">` : `<span class="person-avatar-placeholder">👤</span>`}
                    </div>
                    <div class="person-meta">
                        <div class="person-top-line">
                            <span class="person-name-txt">${escapeHtml(p.name)}</span>
                            <span class="role-pill ${roleBadgeClass}">${roleLabel}</span>
                        </div>
                        <div class="person-sub-txt">
                            <span>ID #${p.id}</span>
                            <span>•</span>
                            <span>${p.sample_count || 1} uzoraka</span>
                            ${p.created_at ? `<span>•</span><span>${escapeHtml(p.created_at.slice(0, 10))}</span>` : ''}
                        </div>
                        ${p.notes ? `<div class="person-notes-txt">📝 ${escapeHtml(p.notes)}</div>` : ''}
                        <div class="person-action-row">
                            <button type="button" class="person-edit-btn" onclick="openPersonModal(${p.id})">
                                ✏️ Uredi podatke
                            </button>
                            <button type="button" class="person-add-snap-btn" onclick="event.stopPropagation(); quickEnrollFor('${escapeHtml(p.name)}', '${p.role || 'standard'}')">
                                📸 Dodaj sliku
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        listEl.innerHTML = `<div style="font-size:0.8rem;color:var(--accent-red);padding:12px;">Greška pri pretrazi baze: ${escapeHtml(err.message)}</div>`;
    }
}

function goToEnrollTab() {
    triggerHaptic('light');
    const enrollBtn = document.querySelector('.bottom-nav .nav-item[data-tab="tab-enroll"]');
    if (enrollBtn) enrollBtn.click();
}

function quickEnrollFor(name, role = 'standard') {
    triggerHaptic('medium');
    goToEnrollTab();
    const nameInput = document.getElementById('enrollName');
    if (nameInput) {
        nameInput.value = name;
    }
    const cleanRole = (role || 'standard').toLowerCase();
    document.querySelectorAll('.role-selector .role-btn').forEach(btn => {
        if (btn.dataset.role === cleanRole) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    document.querySelector('.app-content')?.scrollTo({ top: 0, behavior: 'smooth' });
    showToast(`📸 Dodavanje novog uzorka za: ${name}`);
}

async function quickEnrollNewFace(idx) {
    triggerHaptic('medium');
    const f = window._lastSearchResults?.[idx];
    goToEnrollTab();

    const nameInput = document.getElementById('enrollName');
    if (f && f.status === 'Moguće poklapanje' && f.person_name && f.person_name !== 'Nepoznato' && f.person_name !== 'Nepoznat') {
        if (nameInput) nameInput.value = f.person_name;
    }

    if (f && f.query_crop_base64) {
        try {
            const byteCharacters = atob(f.query_crop_base64);
            const byteNumbers = new Array(byteCharacters.length);
            for (let i = 0; i < byteCharacters.length; i++) {
                byteNumbers[i] = byteCharacters.charCodeAt(i);
            }
            const byteArray = new Uint8Array(byteNumbers);
            const blob = new Blob([byteArray], { type: 'image/jpeg' });
            state.enrollBlob = blob;

            const preview = document.getElementById('enrollPreviewImg');
            const placeholder = document.getElementById('enrollPlaceholder');
            if (preview && placeholder) {
                preview.src = `data:image/jpeg;base64,${f.query_crop_base64}`;
                preview.style.display = 'block';
                placeholder.style.display = 'none';
            }
        } catch (e) {
            console.error('Error transferring face crop:', e);
        }
    } else if (state.capturedBlob) {
        state.enrollBlob = state.capturedBlob;
        const preview = document.getElementById('enrollPreviewImg');
        const placeholder = document.getElementById('enrollPlaceholder');
        if (preview && placeholder) {
            preview.src = URL.createObjectURL(state.capturedBlob);
            preview.style.display = 'block';
            placeholder.style.display = 'none';
        }
    }

    document.querySelector('.app-content')?.scrollTo({ top: 0, behavior: 'smooth' });
    if (nameInput) nameInput.focus();
    showToast('➕ Lice je prebačeno! Upišite ime i spremite.');
}

function resetScanAndRetake() {
    triggerHaptic('light');
    const resultCard = document.getElementById('scanResultCard');
    if (resultCard) resultCard.style.display = 'none';
    clearScanPhoto();
    openLiveCamera('scan');
}

// =========================================================================
// 6b. PERSON DETAILS & EDIT MODAL (SKOČNI PROZOR)
// =========================================================================

let currentEditingPerson = null;

async function openPersonModal(personIdOrName) {
    triggerHaptic('light');
    const modal = document.getElementById('personDetailModal');
    if (!modal) return;

    // Reset fields & show loading skeleton
    const editId = document.getElementById('editPersonId');
    const editName = document.getElementById('editPersonName');
    const editNotes = document.getElementById('editPersonNotes');
    const titleEl = document.getElementById('modalPersonTitle');
    const subTitleEl = document.getElementById('modalPersonSubtitle');
    const avatarBox = document.getElementById('modalAvatarPreview');
    const strip = document.getElementById('modalSamplesStrip');

    // 1. Instant Cache Lookup (from memory) so modal opens in 0ms without waiting for network!
    let cached = null;
    const isNum = typeof personIdOrName === 'number' || (!isNaN(Number(personIdOrName)) && Number(personIdOrName) > 0);
    if (isNum) {
        const numId = Number(personIdOrName);
        cached = window._directoryPersons ? window._directoryPersons[numId] : null;
        if (!cached && window._lastSearchResults) {
            const found = window._lastSearchResults.find(f => Number(f.person_id) === numId);
            if (found) {
                cached = {
                    id: found.person_id,
                    name: found.person_name || found.name,
                    role: found.role,
                    notes: found.notes,
                    sample_count: found.sample_count,
                    thumbnail_base64: found.sample_image_base64
                };
            }
        }
    } else {
        const strName = String(personIdOrName || '').trim().toLowerCase();
        if (window._directoryPersons) {
            cached = Object.values(window._directoryPersons).find(p => (p.name || '').toLowerCase() === strName);
        }
        if (!cached && window._lastSearchResults) {
            const found = window._lastSearchResults.find(f => (f.person_name || f.name || '').toLowerCase() === strName);
            if (found) {
                cached = {
                    id: found.person_id,
                    name: found.person_name || found.name,
                    role: found.role,
                    notes: found.notes,
                    sample_count: found.sample_count,
                    thumbnail_base64: found.sample_image_base64
                };
            }
        }
    }

    if (cached) {
        currentEditingPerson = cached;
        if (editId) editId.value = cached.id || '';
        if (editName) editName.value = cached.name || '';
        if (editNotes) editNotes.value = cached.notes || '';
        if (titleEl) titleEl.textContent = cached.name || 'Osoba';
        if (subTitleEl) subTitleEl.textContent = `ID #${cached.id || '--'} • ${cached.sample_count || 1} uzoraka u bazi`;
        setEditModalRole(cached.role || 'standard');

        if (avatarBox) {
            if (cached.thumbnail_base64) {
                avatarBox.innerHTML = `<img src="data:image/jpeg;base64,${cached.thumbnail_base64}" alt="${escapeHtml(cached.name)}">`;
            } else {
                avatarBox.innerHTML = '<span class="avatar-placeholder">👤</span>';
            }
        }
    } else {
        if (editId) editId.value = '';
        if (editName) editName.value = 'Učitavanje...';
        if (editNotes) editNotes.value = '';
        if (titleEl) titleEl.textContent = 'Učitavanje podataka...';
        if (subTitleEl) subTitleEl.textContent = 'Dohvaćam detalje iz baze...';
        if (avatarBox) avatarBox.innerHTML = '<span class="avatar-placeholder">⏳</span>';
    }

    if (strip) {
        strip.style.display = 'none';
        strip.innerHTML = '';
    }

    // Instantly display modal
    modal.style.display = 'flex';
    modal.classList.add('active');

    try {
        let p = null;
        let samples = [];

        // Fetch full person details & face crop samples from API
        if (isNum) {
            const resp = await fetch(`${API_BASE}/api/v1/persons/${personIdOrName}`);
            if (resp.ok) {
                const data = await resp.json();
                p = data.person;
                samples = p.samples || [];
            }
        }

        // Fallback search by name if not found by ID
        if (!p) {
            const queryName = String(personIdOrName || (cached ? cached.name : '')).trim();
            if (queryName) {
                const resp = await fetch(`${API_BASE}/api/v1/persons?limit=5&query=${encodeURIComponent(queryName)}`);
                if (resp.ok) {
                    const data = await resp.json();
                    const list = data.persons || [];
                    const exact = list.find(item => item.name.toLowerCase() === queryName.toLowerCase()) || list[0];
                    if (exact) {
                        const dResp = await fetch(`${API_BASE}/api/v1/persons/${exact.id}`);
                        if (dResp.ok) {
                            const dData = await dResp.json();
                            p = dData.person;
                            samples = p.samples || [];
                        } else {
                            p = exact;
                        }
                    }
                }
            }
        }

        if (!p && !cached) {
            showToast('⚠️ Osoba nije pronađena u bazi.');
            closePersonModal();
            return;
        }

        if (p) {
            currentEditingPerson = p;

            // Populate updated fields
            if (editId) editId.value = p.id;
            if (editName) editName.value = p.name || '';
            if (editNotes) editNotes.value = p.notes || '';
            if (titleEl) titleEl.textContent = p.name || 'Osoba';
            if (subTitleEl) subTitleEl.textContent = `ID #${p.id} • ${samples.length || p.sample_count || 1} uzoraka u bazi`;

            const role = (p.role || 'standard').toLowerCase();
            setEditModalRole(role);

            // Date & meta
            const createdDate = p.created_at ? p.created_at.slice(0, 10) : 'Nedavno';
            const createdEl = document.getElementById('modalCreatedAtTxt');
            if (createdEl) createdEl.textContent = `📅 Dodano: ${createdDate}`;

            const sampleCountEl = document.getElementById('modalSampleCountTxt');
            if (sampleCountEl) sampleCountEl.textContent = `📸 ${samples.length || p.sample_count || 1} uzorak/ka lica`;

            // Avatar thumbnail
            let avatarSrc = '';
            if (samples.length > 0 && samples[0].crop_base64) {
                avatarSrc = `data:image/jpeg;base64,${samples[0].crop_base64}`;
            } else if (p.thumbnail_base64) {
                avatarSrc = `data:image/jpeg;base64,${p.thumbnail_base64}`;
            }

            if (avatarBox) {
                if (avatarSrc) {
                    avatarBox.innerHTML = `<img src="${avatarSrc}" alt="${escapeHtml(p.name)}">`;
                } else {
                    avatarBox.innerHTML = '<span class="avatar-placeholder">👤</span>';
                }
            }

            // Samples strip preview
            if (strip && samples.length > 0) {
                strip.innerHTML = samples.map(s => {
                    const sSrc = s.crop_base64 ? `data:image/jpeg;base64,${s.crop_base64}` : '';
                    return sSrc ? `<img class="modal-sample-thumb" src="${sSrc}" alt="Uzorak #${s.id}">` : '';
                }).filter(Boolean).join('');
                if (strip.children.length > 0) {
                    strip.style.display = 'flex';
                }
            } else if (strip) {
                strip.style.display = 'none';
            }
        }

    } catch (err) {
        console.error('Error fetching details for person modal:', err);
        // If we already loaded cached info, KEEP MODAL OPEN!
        if (!cached) {
            showToast('❌ Greška pri dohvatu podataka: ' + err.message);
            closePersonModal();
        }
    }
}

window.openPersonModal = openPersonModal;

function setEditModalRole(role) {
    const cleanRole = (role || 'standard').toLowerCase();
    const roleBadge = document.getElementById('modalRoleBadge');
    if (roleBadge) {
        roleBadge.className = `modal-person-badge ${cleanRole}`;
        roleBadge.textContent = cleanRole === 'blacklist' ? 'CRNA LISTA' : (cleanRole === 'vip' ? 'VIP' : 'STANDARD');
    }

    document.querySelectorAll('#editRoleSelector .role-btn').forEach(btn => {
        if (btn.dataset.role === cleanRole) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
}

function closePersonModal() {
    triggerHaptic('light');
    const modal = document.getElementById('personDetailModal');
    if (!modal) return;
    modal.classList.remove('active');
    modal.style.display = 'none';
    currentEditingPerson = null;
}

async function savePersonChanges() {
    const personId = document.getElementById('editPersonId')?.value;
    const nameInput = document.getElementById('editPersonName');
    const notesInput = document.getElementById('editPersonNotes');
    const activeRoleBtn = document.querySelector('#editRoleSelector .role-btn.active');

    const newName = nameInput ? nameInput.value.trim() : '';
    const newNotes = notesInput ? notesInput.value.trim() : '';
    const newRole = activeRoleBtn ? activeRoleBtn.dataset.role : 'standard';

    if (!personId) return;
    if (!newName || newName.length < 2) {
        triggerHaptic('warning');
        showToast('⚠️ Ime mora imati najmanje 2 slova.');
        nameInput?.focus();
        return;
    }

    triggerHaptic('medium');
    const saveBtn = document.getElementById('btnSavePersonModal');
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<span class="spinner-small"></span><span>Spremam...</span>';
    }

    try {
        const resp = await fetch(`${API_BASE}/api/v1/persons/${personId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: newName,
                role: newRole,
                notes: newNotes
            })
        });

        const resData = await resp.json();
        if (!resp.ok) {
            throw new Error(resData.detail || resData.error || `HTTP ${resp.status}`);
        }

        triggerHaptic('success');
        showToast(`✅ Podaci za "${newName}" su uspješno ažurirani!`);
        closePersonModal();

        // Update local memory cache immediately
        if (window._directoryPersons && window._directoryPersons[personId]) {
            window._directoryPersons[personId].name = newName;
            window._directoryPersons[personId].role = newRole;
            window._directoryPersons[personId].notes = newNotes;
        }

        // Refresh database directory list
        loadPersonsDirectory(currentPersonsFilter.query, currentPersonsFilter.role);

        // Update any matching cards in current search results
        if (window._lastSearchResults && Array.isArray(window._lastSearchResults)) {
            let updatedAny = false;
            window._lastSearchResults.forEach(f => {
                if (String(f.person_id) === String(personId) || (currentEditingPerson && f.person_name === currentEditingPerson.name)) {
                    f.person_name = newName;
                    f.role = newRole;
                    f.notes = newNotes;
                    updatedAny = true;
                }
            });
            if (updatedAny) {
                const container = document.getElementById('scanResultCard');
                if (container && container.style.display !== 'none' && state.capturedBlob) {
                    renderScanResult({ results: window._lastSearchResults, faces_detected: window._lastSearchResults.length }, state.capturedBlob);
                }
            }
        }
    } catch (err) {
        console.error('Error saving person changes:', err);
        triggerHaptic('error');
        showToast(`❌ Greška pri spremanju: ${err.message}`);
    } finally {
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="18" height="18">
                    <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
                    <polyline points="17 21 17 13 7 13 7 21"/>
                    <polyline points="7 3 7 8 15 8"/>
                </svg>
                <span>SPREMI IZMJENE</span>
            `;
        }
    }
}

function addPhotoToCurrentPerson() {
    if (!currentEditingPerson) return;
    const name = currentEditingPerson.name;
    const role = currentEditingPerson.role || 'standard';
    closePersonModal();
    quickEnrollFor(name, role);
}

async function deleteCurrentPerson() {
    if (!currentEditingPerson) return;
    const p = currentEditingPerson;

    if (!confirm(`Jeste li sigurni da želite trajno obrisati osobu "${p.name}" (ID #${p.id}) i sve njezine uzorke lica iz baze podataka?`)) {
        return;
    }

    triggerHaptic('heavy');
    try {
        const resp = await fetch(`${API_BASE}/api/v1/persons/${p.id}`, {
            method: 'DELETE'
        });
        const resData = await resp.json();
        if (!resp.ok) {
            throw new Error(resData.detail || resData.error || `HTTP ${resp.status}`);
        }

        triggerHaptic('success');
        showToast(`🗑️ Osoba "${p.name}" je obrisana iz baze.`);
        closePersonModal();
        loadPersonsDirectory(currentPersonsFilter.query, currentPersonsFilter.role);
        loadSystemStatus();
    } catch (err) {
        console.error('Error deleting person:', err);
        triggerHaptic('error');
        showToast(`❌ Greška pri brisanju: ${err.message}`);
    }
}

// =========================================================================
// =========================================================================
// 1b. IN-APP CAMERA & GALLERY SELECTION HELPERS
// =========================================================================

let liveCameraStream = null;
let currentCameraFacing = 'environment';
let activeCameraTarget = 'scan';
let isTorchOn = false;

async function openLiveCamera(target = 'scan') {
    activeCameraTarget = target;
    const modal = document.getElementById('cameraModal');
    const video = document.getElementById('cameraVideo');
    if (!modal || !video) return;

    modal.classList.add('active');
    triggerHaptic('light');

    // 1. Check if we already have an authorized live stream to reuse without re-prompting!
    const activeTrack = liveCameraStream?.getVideoTracks()?.[0];
    if (activeTrack && activeTrack.readyState === 'live') {
        activeTrack.enabled = true;
        try {
            if (video.srcObject !== liveCameraStream) {
                video.srcObject = liveCameraStream;
            }
            await video.play();
            return;
        } catch (e) {
            console.warn('Reusing active track failed, requesting fresh stream:', e);
        }
    }

    // 2. Request stream once (Telegram will prompt permission once per session)
    try {
        const constraints = {
            video: {
                facingMode: { ideal: currentCameraFacing },
                width: { ideal: 1920 },
                height: { ideal: 1080 }
            },
            audio: false
        };
        liveCameraStream = await navigator.mediaDevices.getUserMedia(constraints);
        video.srcObject = liveCameraStream;
        await video.play();
    } catch (err) {
        console.warn('getUserMedia error:', err);
        closeLiveCamera(true);
        showToast('⚠️ Kamera nije dostupna, biram iz galerije...');
        triggerGalleryPicker(target);
    }
}

function closeLiveCamera(forceStop = false) {
    const modal = document.getElementById('cameraModal');
    const video = document.getElementById('cameraVideo');

    if (video) {
        try { video.pause(); } catch (e) {}
    }

    if (liveCameraStream) {
        if (forceStop) {
            // Completely terminate tracks on explicit camera switch or page close
            liveCameraStream.getTracks().forEach(t => t.stop());
            liveCameraStream = null;
        } else {
            // Keep permission session alive, but pause hardware sensor/LED
            liveCameraStream.getVideoTracks().forEach(t => {
                t.enabled = false;
            });
        }
    }

    if (modal) modal.classList.remove('active');
    isTorchOn = false;
}

function takeLiveSnapshot() {
    const video = document.getElementById('cameraVideo');
    if (!video || !video.videoWidth) return;

    triggerHaptic('heavy');
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    canvas.toBlob((blob) => {
        if (!blob) return;
        const file = new File([blob], `capture_${Date.now()}.jpg`, { type: 'image/jpeg' });
        // Close modal and pause sensor, keeping permission authorization cached!
        closeLiveCamera(false);

        if (activeCameraTarget === 'scan') {
            handleScanFile(file);
        } else if (activeCameraTarget === 'compare1') {
            handleCompareFile(1, file);
        } else if (activeCameraTarget === 'compare2') {
            handleCompareFile(2, file);
        } else if (activeCameraTarget === 'enroll') {
            handleEnrollFile(file);
        }
    }, 'image/jpeg', 0.95);
}

function flipCameraFacing() {
    triggerHaptic('light');
    currentCameraFacing = (currentCameraFacing === 'environment') ? 'user' : 'environment';
    // Force stop existing track to switch facing mode
    closeLiveCamera(true);
    openLiveCamera(activeCameraTarget);
}

window.addEventListener('beforeunload', () => {
    closeLiveCamera(true);
});

async function toggleCameraTorch() {
    if (!liveCameraStream) return;
    const track = liveCameraStream.getVideoTracks()[0];
    if (!track) return;
    try {
        isTorchOn = !isTorchOn;
        await track.applyConstraints({
            advanced: [{ torch: isTorchOn }]
        });
        triggerHaptic('light');
    } catch (e) {
        console.log('Torch not supported on this track');
    }
}

function triggerGalleryPicker(target = 'scan') {
    let inputId = 'fileInputScanGallery';
    if (target === 'compare1') inputId = 'fileSlot1';
    else if (target === 'compare2') inputId = 'fileSlot2';
    else if (target === 'enroll') inputId = 'fileEnrollGallery';

    const inp = document.getElementById(inputId);
    if (inp) {
        inp.value = '';
        inp.click();
    }
}

// 7. NAVIGATION & GLOBAL EVENT WIRING
// =========================================================================

document.addEventListener('DOMContentLoaded', () => {
    // Tab switching
    document.querySelectorAll('.bottom-nav .nav-item').forEach(btn => {
        btn.addEventListener('click', () => {
            triggerHaptic('light');
            const targetTab = btn.dataset.tab;

            document.querySelectorAll('.bottom-nav .nav-item').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            const pane = document.getElementById(targetTab);
            if (pane) pane.classList.add('active');

            if (targetTab === 'tab-system') {
                loadSystemStatus();
            }
        });
    });

    // Person Database Directory Search & Filters
    const inputSearch = document.getElementById('inputSearchPersons');
    const clearSearchBtn = document.getElementById('btnClearPersonSearch');

    inputSearch?.addEventListener('input', (e) => {
        const val = e.target.value;
        if (clearSearchBtn) clearSearchBtn.style.display = val ? 'block' : 'none';
        clearTimeout(searchDebounceTimer);
        searchDebounceTimer = setTimeout(() => {
            currentPersonsFilter.query = val;
            loadPersonsDirectory(currentPersonsFilter.query, currentPersonsFilter.role);
        }, 250);
    });

    clearSearchBtn?.addEventListener('click', () => {
        if (inputSearch) inputSearch.value = '';
        clearSearchBtn.style.display = 'none';
        currentPersonsFilter.query = '';
        loadPersonsDirectory('', currentPersonsFilter.role);
    });

    document.getElementById('btnRefreshPersons')?.addEventListener('click', () => {
        triggerHaptic('light');
        loadPersonsDirectory(currentPersonsFilter.query, currentPersonsFilter.role);
        showToast('🔄 Baza osoba osvježena');
    });

    document.querySelectorAll('.role-filter-row .filter-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            triggerHaptic('light');
            document.querySelectorAll('.role-filter-row .filter-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            currentPersonsFilter.role = chip.dataset.filter || 'all';
            loadPersonsDirectory(currentPersonsFilter.query, currentPersonsFilter.role);
        });
    });

    // Header actions
    document.getElementById('btnRefreshHeader')?.addEventListener('click', () => {
        triggerHaptic('light');
        loadSystemStatus();
        showToast('🔄 Status osvježen');
    });

    document.getElementById('btnLockApp')?.addEventListener('click', lockSession);

    // Tab 1: Photo Scan actions
    const scanUploadZone = document.getElementById('scanUploadZone');
    const fileInputScan = document.getElementById('fileInputScan');
    const fileInputScanCamera = document.getElementById('fileInputScanCamera');
    const fileInputScanGallery = document.getElementById('fileInputScanGallery');
    const btnScanCamera = document.getElementById('btnScanCamera');
    const btnScanGallery = document.getElementById('btnScanGallery');
    const btnRemoveScanPhoto = document.getElementById('btnRemoveScanPhoto');
    const btnExecuteSearch = document.getElementById('btnExecuteSearch');

    // Clean input values when clicked so selecting same photo triggers change
    document.querySelectorAll('input[type="file"]').forEach(inp => {
        inp.addEventListener('click', (e) => {
            e.stopPropagation();
            inp.value = '';
        });
    });

    fileInputScan?.addEventListener('change', (e) => {
        const file = e.target.files?.[0];
        if (file) handleScanFile(file);
    });

    fileInputScanCamera?.addEventListener('change', (e) => {
        const file = e.target.files?.[0];
        if (file) handleScanFile(file);
    });

    fileInputScanGallery?.addEventListener('change', (e) => {
        const file = e.target.files?.[0];
        if (file) handleScanFile(file);
    });

    btnRemoveScanPhoto?.addEventListener('click', (e) => {
        e.stopPropagation();
        clearScanPhoto();
    });

    btnExecuteSearch?.addEventListener('click', () => {
        executeSearch();
    });

    // Compare file listeners
    document.getElementById('fileSlot1')?.addEventListener('change', (e) => handleCompareFile(1, e.target.files?.[0]));
    document.getElementById('fileSlot1Camera')?.addEventListener('change', (e) => handleCompareFile(1, e.target.files?.[0]));
    document.getElementById('fileSlot2')?.addEventListener('change', (e) => handleCompareFile(2, e.target.files?.[0]));
    document.getElementById('fileSlot2Camera')?.addEventListener('change', (e) => handleCompareFile(2, e.target.files?.[0]));
    document.getElementById('btnRunCompare')?.addEventListener('click', runComparison);

    // Enroll actions (handled natively via label for="...")

    document.getElementById('fileEnroll')?.addEventListener('change', (e) => handleEnrollFile(e.target.files?.[0]));
    document.getElementById('fileEnrollCamera')?.addEventListener('change', (e) => handleEnrollFile(e.target.files?.[0]));
    document.getElementById('fileEnrollGallery')?.addEventListener('change', (e) => handleEnrollFile(e.target.files?.[0]));

    document.querySelectorAll('.enroll-form .role-btn').forEach(b => {
        b.addEventListener('click', () => {
            triggerHaptic('light');
            document.querySelectorAll('.enroll-form .role-btn').forEach(btn => btn.classList.remove('active'));
            b.classList.add('active');
            state.selectedRole = b.dataset.role;
        });
    });

    document.querySelectorAll('#editRoleSelector .role-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            triggerHaptic('light');
            document.querySelectorAll('#editRoleSelector .role-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const role = btn.dataset.role || 'standard';
            const roleBadge = document.getElementById('modalRoleBadge');
            if (roleBadge) {
                roleBadge.className = `modal-person-badge ${role}`;
                roleBadge.textContent = role === 'blacklist' ? 'CRNA LISTA' : (role === 'vip' ? 'VIP' : 'STANDARD');
            }
        });
    });

    // Person edit modal close listeners
    document.getElementById('btnClosePersonModal')?.addEventListener('click', closePersonModal);
    document.getElementById('personDetailModal')?.addEventListener('click', (e) => {
        if (e.target.id === 'personDetailModal') {
            closePersonModal();
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closePersonModal();
        }
    });

    document.getElementById('btnSubmitEnroll')?.addEventListener('click', submitEnrollment);

    // PIN toggle view in admin
    const pinDisplay = document.getElementById('systemPinDisplay');
    const pinToggleBtn = document.getElementById('btnTogglePinView');
    let pinRevealed = false;
    pinToggleBtn?.addEventListener('click', () => {
        triggerHaptic('light');
        pinRevealed = !pinRevealed;
        if (pinRevealed) {
            pinDisplay.textContent = state.correctPin;
            pinToggleBtn.textContent = 'Sakrij';
        } else {
            pinDisplay.textContent = '••••••';
            pinToggleBtn.textContent = 'Prikaži';
        }
    });

    // Initialize PIN lock screen
    initPinLock();
});
