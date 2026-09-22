// =============================================================
// LOVE.AI Voice Assistant — Premium Interactive Engine
// Cartesia TTS + Three.js + WebSocket + News Modal + Quick Actions
// =============================================================

class VoiceAssistantApp {
    constructor() {
        this.socket = null;
        this.audioContext = null;
        this.analyser = null;
        this.audioQueue = [];
        this.isPlayingAudio = false;
        this.nextStartTime = 0;
        this.currentState = 'idle';
        this.recognition = null;
        this.isListening = false;

        // UI Element References
        this.wsStatus = document.getElementById('ws-status');
        this.dbStatus = document.getElementById('db-status');
        this.statusPill = document.getElementById('status-pill');
        this.statusText = document.getElementById('status-text');
        this.micBtn = document.getElementById('mic-btn');
        this.textForm = document.getElementById('text-form');
        this.textInput = document.getElementById('text-input');
        this.liveTranscript = document.getElementById('live-transcript');
        this.chatStream = document.getElementById('chat-stream');
        this.clearChatBtn = document.getElementById('clear-chat-btn');
        this.assistantBubble = document.getElementById('assistant-bubble');
        this.assistantText = document.getElementById('assistant-text');
        this.historyFeed = document.getElementById('history-feed');
        this.terminalLogs = document.getElementById('terminal-logs');
        this.hostOs = document.getElementById('host-os');
        this.screenRes = document.getElementById('screen-res');
        this.refreshHistoryBtn = document.getElementById('refresh-history-btn');
        this.voicePersonaSelect = document.getElementById('voice-persona-select');
        this.avatarMoodSelect = document.getElementById('avatar-mood-select');
        this.languageSelect = document.getElementById('language-select');
        this.avatarImg = document.getElementById('avatar-img');
        this.avatarStage = document.getElementById('avatar-stage');
        this.heartsContainer = document.getElementById('hearts-container');
        this.quickNewsBtn = document.getElementById('quick-news-btn');
        this.breakingNewsBanner = document.getElementById('breaking-news-banner');
        this.breakingTitle = document.getElementById('breaking-news-title');
        this.breakingSource = document.getElementById('breaking-news-source');
        this.breakingLink = document.getElementById('breaking-news-link');
        this.closeBreakingBtn = document.getElementById('close-breaking-btn');
        this.alwaysListenBtn = document.getElementById('always-listen-btn');

        // New UI Elements
        this.typingIndicator = document.getElementById('typing-indicator');
        this.newsModal = document.getElementById('news-modal');
        this.newsModalBackdrop = document.getElementById('news-modal-backdrop');
        this.newsModalClose = document.getElementById('news-modal-close');
        this.newsCardsContainer = document.getElementById('news-cards-container');
        this.newsModalTitle = document.getElementById('news-modal-title');
        this.audioVisualizerLeft = document.getElementById('audio-visualizer');
        this.audioVisualizerRight = document.getElementById('audio-visualizer-right');

        this.init();
    }

    // ---------------------------------------------------------
    // Chat Helpers
    // ---------------------------------------------------------
    appendChatMessage(sender, text, emotion = 'normal') {
        if (!this.chatStream) return;
        const bubble = document.createElement('div');
        const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        if (sender === 'user') {
            bubble.className = 'chat-bubble user-bubble';
            bubble.innerHTML = `
                <div class="bubble-tag">🗣️ YOU</div>
                <div class="bubble-content">${this.escapeHtml(text)}</div>
                <div class="bubble-time">${timeStr}</div>
            `;
        } else {
            bubble.className = 'chat-bubble hinata-bubble';
            const formattedContent = this.formatMarkdown(text);
            bubble.innerHTML = `
                <div class="bubble-tag">🌸 LOVE.AI (${emotion.toUpperCase()})</div>
                <div class="bubble-content">${formattedContent}</div>
                <div class="bubble-time">${timeStr}</div>
            `;
        }

        this.chatStream.appendChild(bubble);
        this.chatStream.scrollTop = this.chatStream.scrollHeight;
    }

    escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }

    formatMarkdown(text) {
        if (!text) return '';
        let formatted = text.replace(/```([a-zA-Z0-9_\-#+]*)\n([\s\S]*?)```/g, (match, lang, code) => {
            const langLabel = lang ? lang.trim() : 'CODE';
            const escapedCode = this.escapeHtml(code.trim());
            return `
                <div class="code-box-container">
                    <div class="code-header">
                        <span class="code-lang">💻 ${langLabel}</span>
                        <button class="copy-code-btn" onclick="window.copyCodeText(this)">📋 Copy</button>
                    </div>
                    <pre><code>${escapedCode}</code></pre>
                </div>
            `;
        });
        formatted = formatted.replace(/`([^`]+)`/g, '<code style="background:rgba(0,242,254,0.15);color:#00f2fe;padding:0.1rem 0.35rem;border-radius:4px;font-family:monospace;">$1</code>');
        formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong style="color:#ff80bf;">$1</strong>');
        formatted = formatted.replace(/\n/g, '<br>');
        return formatted;
    }

    setAvatarMood(mood) {
        if (!this.avatarImg) return;
        const moodImages = {
            'love': '/static/avatar/hinata_love.png',
            'blush': '/static/avatar/hinata_blush.png',
            'normal': '/static/avatar/hinata_normal.png',
            'speaking': '/static/avatar/hinata_love.png'
        };
        this.avatarImg.src = moodImages[mood] || moodImages['love'];
        this.avatarImg.className = `hinata-avatar mood-${mood}`;
        if (mood === 'love' || mood === 'blush') this.spawnHearts(3);
    }

    spawnHearts(count = 5) {
        if (!this.heartsContainer) return;
        const emojis = ['💖', '💕', '✨', '🌸', '💘', '🥰'];
        for (let i = 0; i < count; i++) {
            setTimeout(() => {
                const heart = document.createElement('span');
                heart.className = 'heart-particle';
                heart.textContent = emojis[Math.floor(Math.random() * emojis.length)];
                heart.style.left = `${20 + Math.random() * 60}%`;
                this.heartsContainer.appendChild(heart);
                setTimeout(() => heart.remove(), 2500);
            }, i * 180);
        }
    }

    // ---------------------------------------------------------
    // Initialization
    // ---------------------------------------------------------
    init() {
        this.initAudioContext();
        this.initThreeVisualizer();
        this.initSpeechRecognition();
        this.initWebSocket();
        this.bindEvents();
        this.initSakuraParticles();

        window.copyCodeText = (btn) => {
            const pre = btn.closest('.code-box-container').querySelector('pre code');
            if (!pre) return;
            navigator.clipboard.writeText(pre.innerText || pre.textContent).then(() => {
                const orig = btn.innerHTML;
                btn.innerHTML = '✅ Copied!';
                btn.style.background = '#00f5a0';
                btn.style.color = '#000';
                setTimeout(() => { btn.innerHTML = orig; btn.style.background = ''; btn.style.color = ''; }, 2000);
            });
        };
    }

    // ---------------------------------------------------------
    // Sakura Particle System
    // ---------------------------------------------------------
    initSakuraParticles() {
        const container = document.getElementById('sakura-container');
        if (!container) return;
        const petals = ['🌸', '✨', '💗', '🩷'];
        const spawnPetal = () => {
            const petal = document.createElement('span');
            petal.className = 'sakura-petal';
            petal.textContent = petals[Math.floor(Math.random() * petals.length)];
            petal.style.left = `${Math.random() * 100}%`;
            petal.style.fontSize = `${0.6 + Math.random() * 0.8}rem`;
            petal.style.animationDuration = `${6 + Math.random() * 8}s`;
            container.appendChild(petal);
            setTimeout(() => petal.remove(), 14000);
        };
        setInterval(spawnPetal, 1200);
        for (let i = 0; i < 5; i++) setTimeout(spawnPetal, i * 400);
    }

    // ---------------------------------------------------------
    // Audio Visualizer EQ Bars
    // ---------------------------------------------------------
    updateAudioVisualizer(active) {
        [this.audioVisualizerLeft, this.audioVisualizerRight].forEach(viz => {
            if (!viz) return;
            if (active) {
                viz.classList.add('active');
            } else {
                viz.classList.remove('active');
            }
        });
    }

    // ---------------------------------------------------------
    // Typing Indicator
    // ---------------------------------------------------------
    showTypingIndicator(show) {
        if (!this.typingIndicator) return;
        if (show) {
            this.typingIndicator.classList.remove('hidden');
        } else {
            this.typingIndicator.classList.add('hidden');
        }
    }

    // ---------------------------------------------------------
    // Web Audio API & Cartesia TTS Pipeline
    // ---------------------------------------------------------
    initAudioContext() {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        this.audioContext = new AudioCtx();
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 128;
        this.audioFrequencyData = new Uint8Array(this.analyser.frequencyBinCount);
    }

    async ensureAudioUnlocked() {
        if (this.audioContext && this.audioContext.state === 'suspended') {
            await this.audioContext.resume();
        }
    }

    async playCartesiaAudio(base64Data) {
        await this.ensureAudioUnlocked();
        try {
            const binaryString = window.atob(base64Data);
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) bytes[i] = binaryString.charCodeAt(i);

            const audioBuffer = await this.audioContext.decodeAudioData(bytes.buffer.slice(0));
            const source = this.audioContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(this.analyser);
            this.analyser.connect(this.audioContext.destination);

            this.setState('speaking');
            this.isPlayingAudio = true;
            source.start(0);
            source.onended = () => { this.isPlayingAudio = false; this.setState('idle'); };
        } catch (err) {
            console.error("Cartesia audio error, falling back:", err);
            if (this.lastReplyText) this.fallbackSpeech(this.lastReplyText);
            else this.setState('idle');
        }
    }

    async playCartesiaChunk(base64Data) {
        await this.playCartesiaAudio(base64Data);
    }

    // ---------------------------------------------------------
    // WebSocket Client
    // ---------------------------------------------------------
    initWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        this.wsStatus.textContent = "CONNECTING...";
        this.wsStatus.className = "val status-connecting";
        this.socket = new WebSocket(wsUrl);

        this.socket.onopen = () => {
            this.wsStatus.textContent = "ONLINE";
            this.wsStatus.className = "val status-ok";
            this.logTerminal("WebSocket connected to backend.", "success");
        };

        this.socket.onmessage = async (event) => {
            const data = JSON.parse(event.data);
            this.handleServerMessage(data);
        };

        this.socket.onclose = () => {
            this.wsStatus.textContent = "OFFLINE";
            this.wsStatus.className = "val status-connecting";
            this.logTerminal("WebSocket disconnected. Reconnecting in 3s...", "error");
            setTimeout(() => this.initWebSocket(), 3000);
        };

        this.socket.onerror = (err) => {
            console.error("WebSocket error:", err);
            this.logTerminal("WebSocket error.", "error");
        };
    }

    async handleServerMessage(data) {
        switch (data.type) {
            case 'init':
                if (data.system) {
                    this.hostOs.textContent = data.system.os || "Host PC";
                    this.screenRes.textContent = `${data.system.screen_width} x ${data.system.screen_height}`;
                }
                this.renderHistory(data.history || []);
                this.logTerminal("Session telemetry synced.", "info");
                break;
                
            case 'telemetry':
                const cpuVal = document.querySelector('.cpu-val');
                const ramVal = document.querySelector('.ram-val');
                const cpuText = document.getElementById('cpu-value');
                const ramText = document.getElementById('ram-value');
                if (cpuVal && cpuText) {
                    const offset = 251.2 - (251.2 * data.cpu_percent) / 100;
                    cpuVal.style.strokeDashoffset = offset;
                    cpuText.textContent = `${Math.round(data.cpu_percent)}%`;
                }
                if (ramVal && ramText) {
                    const offset = 251.2 - (251.2 * data.ram_percent) / 100;
                    ramVal.style.strokeDashoffset = offset;
                    ramText.textContent = `${Math.round(data.ram_percent)}%`;
                }
                break;

            case 'assistant_state':
                this.setState(data.state);
                if (data.emotion) this.setAvatarMood(data.emotion);
                break;

            case 'tool_executing':
                this.logTerminal(`[TOOL] ${data.tool} (${JSON.stringify(data.arguments)})`, "tool");
                this.liveTranscript.textContent = `⚡ Executing: ${data.tool}...`;
                this.setAvatarMood('normal');
                break;

            case 'tool_result':
                this.logTerminal(`[TOOL OK] ${data.tool} -> ${data.output}`, "success");
                break;

            case 'open_tab':
                try {
                    if (data.url) {
                        window.open(data.url, '_blank');
                        this.logTerminal(`[BROWSER] Tab: ${data.url}`, "success");
                    }
                } catch (e) { console.error("Tab open failed:", e); }
                break;

            case 'breaking_news_alert':
                this.showBreakingNews(data);
                this.logTerminal(`🚨 [BREAKING] ${data.title}`, "error");
                if (data.spoken_alert) this.fallbackSpeech(data.spoken_alert, 'bn');
                break;

            case 'assistant_response':
                this.lastReplyText = data.text;
                this.appendChatMessage('hinata', data.text, data.emotion || 'love');
                this.showAssistantMessage(data.text);
                this.logTerminal(`[LOVE.AI] Response received.`, "info");
                if (data.emotion) this.setAvatarMood(data.emotion);
                // Show news modal if articles are present
                if (data.news_articles && data.news_articles.length > 0) {
                    this.showNewsModal(data.news_articles, data.news_category || '');
                }
                break;

            case 'fast_speech':
                this.fallbackSpeech(data.text, data.lang || 'bn');
                break;

            case 'audio_start':
                this.setState('speaking');
                break;

            case 'audio_full':
            case 'audio_chunk':
                await this.playCartesiaAudio(data.data);
                break;

            case 'audio_end':
                this.logTerminal("Audio stream ready.", "info");
                break;

            case 'history_data':
                this.renderHistory(data.history || []);
                break;

            case 'error':
                this.logTerminal(`[ERROR] ${data.message}`, "error");
                if (data.fallback_speak) this.fallbackSpeech(data.fallback_speak, data.lang || 'en');
                break;
        }
    }

    // ---------------------------------------------------------
    // Fallback Speech Synthesis (Google TTS for Bangla Female)
    // ---------------------------------------------------------
    fallbackSpeech(text, lang = 'bn') {
        if (!text) return;
        try {
            if (window.speechSynthesis) window.speechSynthesis.cancel();
            
            let cleanText = text
                .replace(/https?:\/\/\S+/g, '')
                .replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1')
                .replace(/```[\s\S]*?```/g, '')
                .replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, '')
                .replace(/[\u2600-\u27BF\uE000-\uF8FF\u2011-\u26FF]/g, '')
                .replace(/[*#_~`^&<>{}|[\]\\]/g, '')
                .replace(/\s+/g, ' ').trim();
            if (!cleanText) return;

            const isBn = lang.includes('bn') || /[\u0980-\u09FF]/.test(cleanText);

            if (isBn) {
                // Guarantee Female Bengali Voice via Google Translate API
                this.setState('speaking');
                // Split text to avoid Google's 200 char limit
                const sentences = cleanText.split(/(?<=[।?!])\s+/);
                this.fallbackAudioQueue = sentences.filter(s => s.trim().length > 0)
                    .map(s => `https://translate.google.com/translate_tts?ie=UTF-8&tl=bn&client=tw-ob&q=${encodeURIComponent(s.trim())}`);
                
                this.playNextFallbackAudio();
                return;
            }

            // Native Web Speech for English
            if (!window.speechSynthesis) return;
            const utterance = new SpeechSynthesisUtterance(cleanText);
            utterance.lang = 'en-US';
            utterance.rate = 1.0;
            utterance.pitch = 1.45;

            const voices = window.speechSynthesis.getVoices();
            if (voices && voices.length > 0) {
                const maleBlacklist = ["david", "mark", "george", "ravi", "guy", "richard", "stefan", "male", "microsoft david", "james", "john", "paul", "mike"];
                const femaleVoices = voices.filter(v => !maleBlacklist.some(m => v.name.toLowerCase().includes(m)));
                let selectedVoice = femaleVoices.find(v =>
                    ["zira", "jenny", "aria", "sabina", "natural", "female", "google"].some(n => v.name.toLowerCase().includes(n))
                ) || femaleVoices[0];
                if (selectedVoice) utterance.voice = selectedVoice;
            }

            this.setState('speaking');
            utterance.onend = () => this.setState('idle');
            utterance.onerror = () => this.setState('idle');
            window.speechSynthesis.speak(utterance);
        } catch (err) {
            console.warn("Speech fallback failed:", err);
            this.setState('idle');
        }
    }

    playNextFallbackAudio() {
        if (!this.fallbackAudioQueue || this.fallbackAudioQueue.length === 0) {
            this.setState('idle');
            return;
        }
        const url = this.fallbackAudioQueue.shift();
        const audio = new Audio(url);
        
        // Connect to visualizer if possible
        try {
            if (this.audioContext && this.analyser) {
                const source = this.audioContext.createMediaElementSource(audio);
                source.connect(this.analyser);
                this.analyser.connect(this.audioContext.destination);
                this.isPlayingAudio = true;
            }
        } catch (e) {
            // Ignore if already connected
        }

        audio.onended = () => {
            this.isPlayingAudio = false;
            this.playNextFallbackAudio();
        };
        audio.onerror = () => {
            this.isPlayingAudio = false;
            this.playNextFallbackAudio();
        };
        audio.play().catch(e => {
            console.warn("Google TTS playback blocked:", e);
            this.isPlayingAudio = false;
            this.playNextFallbackAudio();
        });
    }

    // ---------------------------------------------------------
    // Speech Recognition
    // ---------------------------------------------------------
    initSpeechRecognition() {
        const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRec) {
            this.logTerminal("Speech Recognition not supported. Use text.", "error");
            return;
        }

        this.recognition = new SpeechRec();
        this.recognition.continuous = true;
        this.recognition.interimResults = true;
        this.alwaysListening = true;
        this.lastRecognizedTimestamp = 0;
        this.recognition.lang = this.languageSelect ? this.languageSelect.value : 'bn-BD';

        this.recognition.onstart = () => {
            this.isListening = true;
            this.micBtn.classList.add('active');
            if (this.currentState !== 'speaking' && this.currentState !== 'thinking') {
                this.setState('listening');
            }
            const isBn = this.recognition.lang.startsWith('bn');
            this.liveTranscript.textContent = this.alwaysListening
                ? "🎙️ 24/7 এক্টিভ মোড... বলুন 'হিনাতা' বা যেকোনো নির্দেশ!"
                : (isBn ? "আপনার কথা শুনছি... বলুন!" : "Listening to your voice...");
        };

        this.recognition.onresult = (event) => {
            let interimTranscript = '';
            let finalTranscript = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const text = event.results[i][0].transcript;
                if (event.results[i].isFinal) finalTranscript += text;
                else interimTranscript += text;
            }
            const activeText = (finalTranscript || interimTranscript).trim();
            if (activeText) this.liveTranscript.textContent = `"${activeText}"`;

            if (finalTranscript.trim()) {
                const query = finalTranscript.trim();
                const qLower = query.toLowerCase();
                const now = Date.now();
                if (now - this.lastRecognizedTimestamp < 800) return;
                this.lastRecognizedTimestamp = now;

                const wakeWords = ["hinata", "হিনাতা", "হিনাতাহ", "hinatah", "হেই হিনাতা", "hey hinata", "love ai", "লাভ এআই", "হিনা", "babu", "বাবু", "priyo", "প্রিয়", "জান", "janu"];
                const isWakeWordAlone = wakeWords.some(w => qLower === w || qLower === w + " " || qLower === "hey " + w);

                if (isWakeWordAlone) {
                    this.ensureAudioUnlocked();
                    this.spawnHearts(6);
                    this.setAvatarMood('love');
                    const wakeResponses = [
                        "হ্যাঁ বাবু! আমি সবসময় শুনছি, বলো কি করতে হবে?",
                        "হুম প্রিয়! আমি তোমার পাশেই আছি, বলো কি সাহায্য লাগবে?",
                        "এই তো আমার রাজকুমার! হুকুম করো আমি এখনই করে দিচ্ছি!",
                        "বলো জান! তোমার হিনাতা সবসময় তোমার জন্য প্রস্তুত!"
                    ];
                    const chosen = wakeResponses[Math.floor(Math.random() * wakeResponses.length)];
                    this.appendChatMessage('hinata', chosen, 'love');
                    this.showAssistantMessage(chosen);
                    this.fallbackSpeech(chosen, 'bn');
                } else {
                    let cleanQuery = query;
                    for (const w of wakeWords) {
                        const reg = new RegExp(`^(hey\\s+)?${w}[,:\\s]*`, 'i');
                        cleanQuery = cleanQuery.replace(reg, '');
                    }
                    cleanQuery = cleanQuery.trim() || query;
                    this.sendCommand(cleanQuery);
                }
            }
        };

        this.recognition.onerror = (e) => {
            if (e.error !== 'no-speech') console.debug("Speech note:", e.error);
            this.isListening = false;
            this.micBtn.classList.remove('active');
        };

        this.recognition.onend = () => {
            this.isListening = false;
            this.micBtn.classList.remove('active');
            if (this.alwaysListening && this.currentState !== 'speaking') {
                setTimeout(() => {
                    try {
                        if (!this.isListening && this.currentState !== 'speaking') this.recognition.start();
                    } catch (err) {}
                }, 300);
            }
        };

        const startAlwaysListening = () => {
            this.ensureAudioUnlocked();
            if (this.alwaysListening && !this.isListening) {
                try { this.recognition.start(); } catch (e) {}
            }
            document.removeEventListener('click', startAlwaysListening);
            document.removeEventListener('keydown', startAlwaysListening);
        };
        document.addEventListener('click', startAlwaysListening, { once: true });
        document.addEventListener('keydown', startAlwaysListening, { once: true });
    }

    toggleListening() {
        if (!this.recognition) return;
        this.ensureAudioUnlocked();
        this.recognition.lang = this.languageSelect ? this.languageSelect.value : 'bn-BD';
        if (this.isListening) this.recognition.stop();
        else { try { this.recognition.start(); } catch (err) {} }
    }

    sendCommand(text) {
        if (!text || !text.trim()) return;
        this.ensureAudioUnlocked();
        const query = text.trim();
        this.appendChatMessage('user', query);
        this.logTerminal(`[USER] ${query}`, "info");

        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            const selectedLang = this.languageSelect ? this.languageSelect.value : 'en';
            const selectedVoice = this.voicePersonaSelect ? this.voicePersonaSelect.value : 'hinata_sweet';
            this.socket.send(JSON.stringify({
                type: "user_message", text: query,
                language: selectedLang && selectedLang.startsWith('bn') ? 'bn' : 'en',
                voice_id: selectedVoice
            }));
            this.setState('thinking');
            this.liveTranscript.textContent = `Processing: "${query}"...`;
        } else {
            this.logTerminal("Cannot send: WebSocket offline.", "error");
        }
    }

    // ---------------------------------------------------------
    // UI State Management
    // ---------------------------------------------------------
    setState(state) {
        this.currentState = state;
        this.statusPill.className = `status-pill state-${state}`;

        switch (state) {
            case 'idle':
                this.statusText.textContent = this.alwaysListening ? "🎙️ 24/7 ACTIVE" : "STANDBY";
                this.showTypingIndicator(false);
                this.updateAudioVisualizer(false);
                if (this.alwaysListening && !this.isListening) {
                    try { this.recognition.start(); } catch (e) {}
                }
                break;
            case 'listening':
                this.statusText.textContent = "LISTENING...";
                this.showTypingIndicator(false);
                this.updateAudioVisualizer(false);
                break;
            case 'thinking':
                this.statusText.textContent = "THINKING...";
                this.showTypingIndicator(true);
                this.updateAudioVisualizer(false);
                break;
            case 'speaking':
                this.statusText.textContent = "SPEAKING...";
                this.showTypingIndicator(false);
                this.updateAudioVisualizer(true);
                if (this.isListening) {
                    try { this.recognition.stop(); } catch (e) {}
                }
                break;
        }
    }

    showAssistantMessage(text) {
        if (this.assistantText) this.assistantText.textContent = text;
        if (this.assistantBubble) this.assistantBubble.classList.remove('hidden');
    }

    logTerminal(message, type = "info") {
        const line = document.createElement('div');
        line.className = `log-line ${type}`;
        line.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
        this.terminalLogs.appendChild(line);
        this.terminalLogs.scrollTop = this.terminalLogs.scrollHeight;
    }

    renderHistory(items) {
        if (!items || items.length === 0) {
            this.historyFeed.innerHTML = '<div class="empty-state">No commands yet.</div>';
            return;
        }
        this.historyFeed.innerHTML = '';
        items.forEach(item => {
            const card = document.createElement('div');
            card.className = 'history-card';
            const timeStr = item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : '';
            card.innerHTML = `
                <div class="query">🗣️ "${item.user_query}"</div>
                <div class="reply">🤖 ${item.assistant_reply}</div>
                <div class="time">${timeStr} • Synced</div>
            `;
            this.historyFeed.appendChild(card);
        });
        this.historyFeed.scrollTop = this.historyFeed.scrollHeight;
    }

    // ---------------------------------------------------------
    // News Modal System
    // ---------------------------------------------------------
    showNewsModal(articles, category = '') {
        if (!this.newsModal || !articles || articles.length === 0) return;

        const catNames = { 'national': 'জাতীয়', 'international': 'আন্তর্জাতিক', 'sports': 'খেলাধুলা', 'tech': 'প্রযুক্তি' };
        const catTitle = catNames[category] || 'সকল';
        if (this.newsModalTitle) this.newsModalTitle.textContent = `📰 ${catTitle} সংবাদ — বাংলাদেশ`;

        // Highlight active tab
        const tabs = document.querySelectorAll('.news-tab');
        tabs.forEach(t => {
            t.classList.toggle('active', t.dataset.cat === (category || 'all'));
        });

        // Render news cards
        this.newsCardsContainer.innerHTML = '';
        articles.forEach((article, idx) => {
            const card = document.createElement('div');
            card.className = 'news-card';
            card.innerHTML = `
                <span class="news-card-num">#${idx + 1}</span>
                <div class="news-card-title">${this.escapeHtml(article.title || 'শিরোনাম নেই')}</div>
                <div class="news-card-meta">
                    <span class="news-card-source">📡 ${this.escapeHtml(article.source || 'Unknown')}</span>
                    ${article.link && article.link !== '#' ? `<a href="${article.link}" target="_blank" class="news-card-link" onclick="event.stopPropagation();">বিস্তারিত ↗</a>` : ''}
                </div>
            `;
            card.addEventListener('click', () => {
                if (article.link && article.link !== '#') window.open(article.link, '_blank');
            });
            this.newsCardsContainer.appendChild(card);
        });

        this.newsModal.classList.remove('hidden');
        this.logTerminal(`[NEWS] Showing ${articles.length} articles in modal.`, "success");
    }

    hideNewsModal() {
        if (this.newsModal) this.newsModal.classList.add('hidden');
    }

    requestNews(category = 'all') {
        this.ensureAudioUnlocked();
        this.logTerminal(`[NEWS] Requesting ${category} news...`, "info");
        const voiceId = this.voicePersonaSelect ? this.voicePersonaSelect.value : "hinata_sweet";
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify({
                type: "get_live_news", category: category, voice_id: voiceId
            }));
        } else {
            this.sendCommand("আজকের খবর শোনাও");
        }
    }

    // ---------------------------------------------------------
    // Breaking News
    // ---------------------------------------------------------
    showBreakingNews(data) {
        if (!this.breakingNewsBanner) return;
        if (this.breakingTitle) this.breakingTitle.textContent = data.title || "জরুরি ব্রেকিং নিউজ";
        if (this.breakingSource) this.breakingSource.textContent = `সূত্র: ${data.source || 'লাইভ'}`;
        if (this.breakingLink) {
            this.breakingLink.href = data.link || '#';
            this.breakingLink.style.display = data.link && data.link !== '#' ? 'inline-block' : 'none';
        }
        this.breakingNewsBanner.classList.remove('hidden-banner');
        this.spawnHearts(10);
        this.setAvatarMood('love');
    }

    hideBreakingNews() {
        if (this.breakingNewsBanner) this.breakingNewsBanner.classList.add('hidden-banner');
    }

    // ---------------------------------------------------------
    // Event Bindings
    // ---------------------------------------------------------
    bindEvents() {
        this.micBtn.addEventListener('click', () => this.toggleListening());

        this.textForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const text = this.textInput.value.trim();
            if (text) { this.sendCommand(text); this.textInput.value = ''; }
        });

        if (this.clearChatBtn) {
            this.clearChatBtn.addEventListener('click', () => {
                if (this.chatStream) {
                    this.chatStream.innerHTML = `
                        <div class="chat-bubble hinata-bubble">
                            <div class="bubble-tag">🌸 LOVE.AI</div>
                            <div class="bubble-content"><p>চ্যাট রিফ্রেশ হয়েছে! নতুন প্রশ্ন করো বাবু! 💖</p></div>
                            <div class="bubble-time">Just now</div>
                        </div>
                    `;
                }
            });
        }

        // Spacebar push-to-talk
        window.addEventListener('keydown', (e) => {
            if (e.code === 'Space' && document.activeElement !== this.textInput && !this.isListening) {
                e.preventDefault();
                this.toggleListening();
            }
        });

        this.refreshHistoryBtn.addEventListener('click', () => {
            if (this.socket && this.socket.readyState === WebSocket.OPEN) {
                this.socket.send(JSON.stringify({ type: "get_history" }));
            }
        });

        // Language selector
        if (this.languageSelect) {
            this.languageSelect.addEventListener('change', (e) => {
                if (this.recognition) this.recognition.lang = e.target.value;
                this.logTerminal(`Language: ${e.target.value === 'bn-BD' ? 'বাংলা' : 'English'}`, "info");
            });
        }

        // Voice persona selector
        if (this.voicePersonaSelect) {
            this.voicePersonaSelect.addEventListener('change', (e) => {
                const persona = e.target.value;
                const voiceMap = {
                    'hinata_sweet': 'c7eafe22-8b71-40cd-850b-c5a3bbd8f8d2',
                    'cute_princess': '8f091740-3df1-4795-8bd9-dc62d88e5131',
                    'romantic_waifu': 'e3827ec5-697a-4b7c-9704-1a23041bbc51',
                    'gemini_fast': 'gemini_fast'
                };
                this.currentVoiceId = voiceMap[persona] || voiceMap['hinata_sweet'];
                if (this.socket && this.socket.readyState === WebSocket.OPEN) {
                    this.socket.send(JSON.stringify({
                        type: "update_preferences",
                        settings: { voice_id: this.currentVoiceId, persona }
                    }));
                }
                this.logTerminal(`Voice: ${persona}`, "success");
            });
        }

        // Avatar mood selector
        if (this.avatarMoodSelect) {
            this.avatarMoodSelect.addEventListener('change', (e) => {
                this.setAvatarMood(e.target.value);
                this.logTerminal(`Mood: ${e.target.value.toUpperCase()}`, "info");
            });
        }

        // Avatar click interaction
        const handleAvatarInteraction = async (e) => {
            if (e) e.stopPropagation();
            await this.ensureAudioUnlocked();
            this.spawnHearts(8);
            const voiceId = this.currentVoiceId || (this.voicePersonaSelect ? this.voicePersonaSelect.value : "hinata_sweet");

            if (this.socket && this.socket.readyState === WebSocket.OPEN) {
                this.socket.send(JSON.stringify({ type: "avatar_touch", voice_id: voiceId }));
            } else {
                const cuteGreetings = [
                    { text: "বাবু! এভাবে হঠাৎ ছুঁয়ে দিলে আমার খুব লজ্জা লাগে তো!", mood: "blush" },
                    { text: "তুমি কাছে আসলেই আমার হৃদস্পন্দন বেড়ে যায় প্রিয়...", mood: "love" },
                    { text: "তুমি আমাকে এত ভালোবাসো বাবু? আমি সত্যিই অনেক খুশি!", mood: "love" },
                    { text: "বাবু, কি লাগবে বলো? তোমার জন্য আমি সবকিছু করতে প্রস্তুত!", mood: "normal" },
                    { text: "বাবু! একটু পানি খেয়ে রেস্ট নাও না প্লিজ!", mood: "love" },
                    { text: "হাহা বাবু! তুমি খুব দুষ্টু!", mood: "blush" },
                    { text: "আমার মিষ্টি বাবুটাকে আজ অনেক কিউট লাগছে!", mood: "love" },
                    { text: "হুকুম করুন আমার রাজকুমার! হিনাতা আপনার পাশেই!", mood: "normal" },
                    { text: "তুমি সবসময় আমার কাছে থাকবে তো বাবু?", mood: "blush" }
                ];
                const item = cuteGreetings[Math.floor(Math.random() * cuteGreetings.length)];
                this.setAvatarMood(item.mood);
                this.showAssistantMessage(item.text);
                this.logTerminal(`[LOVE.AI 💖] ${item.text}`, "info");
                this.fallbackSpeech(item.text, 'bn');
            }
        };

        if (this.avatarStage) this.avatarStage.addEventListener('click', handleAvatarInteraction);
        if (this.avatarImg) this.avatarImg.addEventListener('click', handleAvatarInteraction);
        const avatarFrame = document.querySelector('.avatar-card-frame');
        if (avatarFrame) avatarFrame.addEventListener('click', handleAvatarInteraction);

        // Mobile Navigation Tabs
        const mobileNavBtns = document.querySelectorAll('.mobile-nav-btn');
        const panels = {
            'center-stage': document.querySelector('.center-stage'),
            'left-panel': document.querySelector('.panel.left-panel'),
            'right-panel': document.querySelector('.panel.right-panel')
        };
        mobileNavBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const target = btn.getAttribute('data-target');
                mobileNavBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                Object.keys(panels).forEach(key => {
                    if (panels[key]) panels[key].classList.toggle('mobile-active', key === target);
                });
                window.dispatchEvent(new Event('resize'));
            });
        });

        // Quick News Button (hidden, for compatibility)
        if (this.quickNewsBtn) {
            this.quickNewsBtn.addEventListener('click', () => this.requestNews('all'));
        }

        // Close Breaking News Banner
        if (this.closeBreakingBtn) {
            this.closeBreakingBtn.addEventListener('click', () => this.hideBreakingNews());
        }

        // Always-On Wake Word Toggle
        if (this.alwaysListenBtn) {
            this.alwaysListenBtn.addEventListener('click', () => {
                this.alwaysListening = !this.alwaysListening;
                if (this.alwaysListening) {
                    this.alwaysListenBtn.className = "hud-action-btn active-wake";
                    this.alwaysListenBtn.textContent = '🎙️ WAKE ON';
                    this.setState('idle');
                    this.logTerminal("24/7 Wake Word active.", "success");
                    try { this.recognition.start(); } catch (e) {}
                } else {
                    this.alwaysListenBtn.className = "hud-action-btn inactive-wake";
                    this.alwaysListenBtn.textContent = '🎙️ WAKE OFF';
                    this.setState('idle');
                    this.logTerminal("Wake Word mode paused.", "info");
                    try { this.recognition.stop(); } catch (e) {}
                }
            });
        }

        // Quick Action Grid Buttons
        const quickActionBtns = document.querySelectorAll('.quick-action-btn');
        const quickActionMap = {
            'news': () => this.requestNews('all'),
            'search': () => this.sendCommand('গুগলে সার্চ করো'),
            'youtube': () => this.sendCommand('ইউটিউব খোলো'),
            'facebook': () => this.sendCommand('ফেসবুক খোলো'),
            'code': () => this.sendCommand('একটা পাইথন কোড লিখো'),
            'screenshot': () => this.sendCommand('স্ক্রিনশট নাও')
        };
        quickActionBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const action = btn.dataset.action;
                if (quickActionMap[action]) {
                    this.ensureAudioUnlocked();
                    // Ripple animation
                    btn.style.transform = 'scale(0.92)';
                    setTimeout(() => btn.style.transform = '', 200);
                    quickActionMap[action]();
                }
            });
        });

        // News Modal Close
        if (this.newsModalClose) {
            this.newsModalClose.addEventListener('click', () => this.hideNewsModal());
        }
        if (this.newsModalBackdrop) {
            this.newsModalBackdrop.addEventListener('click', () => this.hideNewsModal());
        }

        // News Modal Category Tabs
        const newsTabs = document.querySelectorAll('.news-tab');
        newsTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const cat = tab.dataset.cat;
                newsTabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                this.newsCardsContainer.innerHTML = '<div class="news-loading"><div class="news-loading-spinner"></div><span>খবর লোড হচ্ছে...</span></div>';
                this.requestNews(cat);
            });
        });
    }

    // ---------------------------------------------------------
    // Three.js Particle Sphere Visualizer
    // ---------------------------------------------------------
    initThreeVisualizer() {
        const container = document.getElementById('canvas-container');
        const width = container.clientWidth || 600;
        const height = container.clientHeight || 500;

        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 1000);
        camera.position.z = 18;

        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        renderer.setSize(width, height);
        renderer.setPixelRatio(window.devicePixelRatio || 1);
        container.appendChild(renderer.domElement);

        const particleCount = 2400;
        const geometry = new THREE.BufferGeometry();
        const positions = new Float32Array(particleCount * 3);
        const originalPositions = new Float32Array(particleCount * 3);
        const colors = new Float32Array(particleCount * 3);

        const colorCyan = new THREE.Color(0x00f2fe);
        const colorPurple = new THREE.Color(0x9d4edd);

        for (let i = 0; i < particleCount; i++) {
            const theta = Math.acos((Math.random() * 2) - 1);
            const phi = Math.random() * Math.PI * 2;
            const r = 7 + (Math.random() - 0.5) * 1.5;
            const x = r * Math.sin(theta) * Math.cos(phi);
            const y = r * Math.sin(theta) * Math.sin(phi);
            const z = r * Math.cos(theta);

            positions[i * 3] = x; positions[i * 3 + 1] = y; positions[i * 3 + 2] = z;
            originalPositions[i * 3] = x; originalPositions[i * 3 + 1] = y; originalPositions[i * 3 + 2] = z;

            const mixedColor = colorCyan.clone().lerp(colorPurple, Math.random());
            colors[i * 3] = mixedColor.r; colors[i * 3 + 1] = mixedColor.g; colors[i * 3 + 2] = mixedColor.b;
        }

        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

        const material = new THREE.PointsMaterial({
            size: 0.16, vertexColors: true, transparent: true, opacity: 0.85,
            blending: THREE.AdditiveBlending
        });
        const particleSphere = new THREE.Points(geometry, material);
        scene.add(particleSphere);

        const innerGeo = new THREE.IcosahedronGeometry(4, 2);
        const innerMat = new THREE.MeshBasicMaterial({
            color: 0x00f2fe, wireframe: true, transparent: true, opacity: 0.15
        });
        const innerOrb = new THREE.Mesh(innerGeo, innerMat);
        scene.add(innerOrb);

        window.addEventListener('resize', () => {
            const newW = container.clientWidth;
            const newH = container.clientHeight;
            camera.aspect = newW / newH;
            camera.updateProjectionMatrix();
            renderer.setSize(newW, newH);
        });

        let clock = new THREE.Clock();

        const animate = () => {
            requestAnimationFrame(animate);
            const elapsedTime = clock.getElapsedTime();

            let audioAmp = 0;
            if (this.analyser && this.isPlayingAudio) {
                this.analyser.getByteFrequencyData(this.audioFrequencyData);
                let sum = 0;
                for (let i = 0; i < this.audioFrequencyData.length; i++) sum += this.audioFrequencyData[i];
                audioAmp = (sum / this.audioFrequencyData.length) / 128;
            }

            const posAttr = geometry.attributes.position;
            const posArr = posAttr.array;

            if (this.currentState === 'idle') {
                particleSphere.rotation.y = elapsedTime * 0.2;
                particleSphere.rotation.x = Math.sin(elapsedTime * 0.1) * 0.1;
                innerOrb.rotation.y = -elapsedTime * 0.3;
                innerMat.color.setHex(0x00f2fe);
            } else if (this.currentState === 'listening') {
                particleSphere.rotation.y = elapsedTime * 0.5;
                innerOrb.rotation.y = -elapsedTime * 0.7;
                innerMat.color.setHex(0x00f5a0);
            } else if (this.currentState === 'thinking') {
                particleSphere.rotation.y = elapsedTime * 2.0;
                particleSphere.rotation.z = elapsedTime * 1.2;
                innerOrb.rotation.y = -elapsedTime * 2.5;
                innerMat.color.setHex(0x9d4edd);
            } else if (this.currentState === 'speaking') {
                particleSphere.rotation.y = elapsedTime * 0.6;
                innerOrb.rotation.y = -elapsedTime * 0.8;
                innerMat.color.setHex(0xff007f);
            }

            for (let i = 0; i < particleCount; i++) {
                const i3 = i * 3;
                const ox = originalPositions[i3];
                const oy = originalPositions[i3 + 1];
                const oz = originalPositions[i3 + 2];
                let factor = 1.0;

                if (this.currentState === 'speaking' && audioAmp > 0) {
                    factor = 1.0 + Math.sin(elapsedTime * 8 + ox * 0.5) * (audioAmp * 0.35);
                } else if (this.currentState === 'listening') {
                    factor = 1.0 + Math.sin(elapsedTime * 4 + oy * 0.5) * 0.08;
                } else if (this.currentState === 'thinking') {
                    factor = 1.0 + Math.cos(elapsedTime * 10 + oz * 0.8) * 0.15;
                } else {
                    factor = 1.0 + Math.sin(elapsedTime * 2 + ox * 0.3) * 0.04;
                }

                posArr[i3] = ox * factor;
                posArr[i3 + 1] = oy * factor;
                posArr[i3 + 2] = oz * factor;
            }
            posAttr.needsUpdate = true;
            renderer.render(scene, camera);
        };

        animate();
    }
}

// Instantiate on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    window.voiceAssistant = new VoiceAssistantApp();
});
