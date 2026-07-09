let sessionState = null;
let sessionId = null;
let currentQuestion = 0;
let totalQuestions = 8;
let stream = null;
let recognition = null;
let synth = window.speechSynthesis;
let selectedVoice = null;
let speechRate = 1.0;
let isAutoMode = true;
let isProcessingResponse = false;
let silenceTimeout = null;
let accumulatedTranscript = '';
let isMicMuted = false;

// Proctoring variables
let faceDetectionModel = null;
let faceCheckInterval = null;
let violations = 0;
let isInterviewActive = false;
let noFaceFrames = 0;
let maxNoFaceFrames = 5;
let tabSwitchCount = 0;
let multipleFaceDetections = 0;
const maxMultipleFaceDetections = 3;

// Helper to provide a fallback coding template if the server doesn't return one
function getDefaultTemplate(language) {
    const templates = {
        'Python': 'def solution(nums):\n    # Write your code here\n    pass',
        'Java': 'public class Solution {\n    public int[] solution(int[] nums) {\n        // Write your code here\n        \n    }\n}',
        'JavaScript': 'function solution(nums) {\n    // Write your code here\n    \n}',
        'C++': 'class Solution {\npublic:\n    vector<int> solution(vector<int>& nums) {\n        // Write your code here\n        \n    }\n};'
    };
    return templates[language] || templates['Python'];
}

// Populate voice selector
function populateVoiceList() {
    const voices = synth.getVoices();
    const voiceSelect = document.getElementById('voiceSelect');
    if (!voiceSelect) return;
    voiceSelect.innerHTML = '';
    
    const englishVoices = voices.filter(voice => voice.lang.startsWith('en'));
    
    if (englishVoices.length === 0) {
        voiceSelect.innerHTML = '<option value="">No voices available</option>';
        return;
    }
    
    englishVoices.forEach((voice, index) => {
        const option = document.createElement('option');
        option.value = index;
        option.textContent = `${voice.name} (${voice.lang})`;
        
        if (voice.name.includes('Google') || voice.name.includes('Samantha') || 
            voice.name.includes('Alex') || voice.name.includes('Microsoft')) {
            option.selected = true;
            selectedVoice = voice;
        }
        
        voiceSelect.appendChild(option);
    });
}

if (synth.onvoiceschanged !== undefined) {
    synth.onvoiceschanged = populateVoiceList;
}

setTimeout(populateVoiceList, 100);

document.addEventListener('DOMContentLoaded', () => {
    populateVoiceList();
    const voiceSelect = document.getElementById('voiceSelect');
    if (voiceSelect) {
        voiceSelect.addEventListener('change', (e) => {
            const voices = synth.getVoices().filter(v => v.lang.startsWith('en'));
            selectedVoice = voices[e.target.value];
            console.log('Selected voice:', selectedVoice.name);
        });
    }
});

async function initFaceDetection() {
    try {
        faceDetectionModel = await blazeface.load();
        console.log('Face detection loaded');
        startFaceMonitoring();
    } catch (error) {
        console.error('Face detection error:', error);
        showStatus('Face detection unavailable - proctoring limited', 'error');
    }
}

function startFaceMonitoring() {
    faceCheckInterval = setInterval(async () => {
        if (!isInterviewActive) return;
        
        const video = document.getElementById('userVideo');
        if (video && video.readyState === 4 && faceDetectionModel) {
            try {
                const predictions = await faceDetectionModel.estimateFaces(video, false);
                
                const highConfidenceFaces = predictions.filter(pred => {
                    const faceSize = (pred.bottomRight[0] - pred.topLeft[0]) * 
                                   (pred.bottomRight[1] - pred.topLeft[1]);
                    const videoSize = video.videoWidth * video.videoHeight;
                    const faceRatio = faceSize / videoSize;
                    return faceRatio > 0.05;
                });
                
                if (highConfidenceFaces.length === 0) {
                    noFaceFrames++;
                    multipleFaceDetections = 0;
                    if (noFaceFrames >= maxNoFaceFrames) {
                        updateSecurityStatus('error', '⚠️', 'No face detected');
                        logViolation('no_face', 'Face not visible');
                    } else {
                        updateSecurityStatus('warning', '⚠️', 'Face detection unclear');
                    }
                } else if (highConfidenceFaces.length > 1) {
                    multipleFaceDetections++;
                    noFaceFrames = 0;
                    
                    if (multipleFaceDetections >= maxMultipleFaceDetections) {
                        updateSecurityStatus('error', '❌', 'Multiple people detected');
                        showWarningPopup(`Multiple people detected (${highConfidenceFaces.length} faces)`);
                        logViolation('multiple_people', `${highConfidenceFaces.length} faces`);
                        multipleFaceDetections = 0;
                    } else {
                        updateSecurityStatus('warning', '⚠️', `Detecting ${highConfidenceFaces.length} faces...`);
                    }
                } else {
                    noFaceFrames = 0;
                    multipleFaceDetections = 0;
                    updateSecurityStatus('valid', '✓', 'Face verified');
                }
            } catch (error) {
                console.error('Face detection error:', error);
            }
        }
    }, 2000);
}

function showWarningPopup(message) {
    const existingWarning = document.getElementById('warningPopup');
    if (existingWarning) existingWarning.remove();
    
    const warningDiv = document.createElement('div');
    warningDiv.id = 'warningPopup';
    warningDiv.className = 'warning-popup';
    warningDiv.innerHTML = `<h3 style="margin: 0 0 10px 0; font-size: 20px;">⚠️ Warning</h3><p style="margin: 0;">${message}</p>`;
    
    document.body.appendChild(warningDiv);
    setTimeout(() => warningDiv.remove(), 5000);
}

document.addEventListener('visibilitychange', () => {
    if (document.hidden && isInterviewActive) {
        tabSwitchCount++;
        logViolation('tab_switch', `Tab switch #${tabSwitchCount}`);
        showWarningPopup('Tab switching detected. Stay on this page during interview.');
    }
});

function logViolation(type, details) {
    violations++;
    updateViolationCounter();
    
    if (sessionState) {
        if (!sessionState.proctoring_violations) {
            sessionState.proctoring_violations = [];
        }
        sessionState.proctoring_violations.push({
            type: type,
            details: details,
            timestamp: new Date().toISOString()
        });
        
        if (type === 'multiple_people' || type === 'disqualified') {
            sessionState.is_disqualified = true;
            isInterviewActive = false;
            isAutoMode = false;
            clearInterval(faceCheckInterval);
            showStatus('Interview terminated due to proctoring violation.', 'error');
            showStep(3);
        }
    }
}

function updateViolationCounter() {
    const counter = document.getElementById('violationCounter');
    const count = document.getElementById('violationCount');
    if (count) count.textContent = violations;
    if (counter) counter.classList.remove('hidden');
}

function updateSecurityStatus(type, icon, text) {
    const indicator = document.getElementById('securityIndicator');
    const secIcon = document.getElementById('securityIcon');
    const secText = document.getElementById('securityText');
    if (indicator) indicator.className = `security-indicator ${type}`;
    if (secIcon) secIcon.textContent = icon;
    if (secText) secText.textContent = text;
}

function updateBotStatus(status, text) {
    const botAvatar = document.getElementById('botAvatar');
    const botStatus = document.getElementById('botStatus');
    
    if (botAvatar) {
        botAvatar.className = 'bot-avatar-large';
        if (status === 'speaking') {
            botAvatar.classList.add('speaking');
        } else if (status === 'listening') {
            botAvatar.classList.add('listening');
        }
    }
    
    if (botStatus) {
        botStatus.className = 'bot-status';
        if (status === 'speaking') {
            botStatus.classList.add('speaking');
            botStatus.textContent = text || 'Speaking...';
        } else if (status === 'listening') {
            botStatus.classList.add('listening');
            botStatus.textContent = text || 'Listening...';
        } else {
            botStatus.textContent = text || 'Ready';
        }
    }
}

async function initCamera() {
    try {
        // Try camera + mic first
        stream = await navigator.mediaDevices.getUserMedia({ 
            video: { width: 1280, height: 720 }, 
            audio: true 
        });
        const video = document.getElementById('userVideo');
        if (video) {
            video.srcObject = stream;
            await new Promise(resolve => {
                video.onloadedmetadata = resolve;
            });
        }
        
        await initFaceDetection();
        updateSecurityStatus('info', '🔍', 'Monitoring active');

    } catch (error) {
        console.error('Camera error:', error);

        // Fallback: try audio-only (mic for speech recognition still needed)
        try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            console.warn('No camera found — continuing with audio only');
            updateSecurityStatus('warning', '⚠️', 'No camera — proctoring disabled');
            showStatus('No camera detected. Continuing without video proctoring.', 'warning');
        } catch (audioError) {
            console.error('Microphone error:', audioError);
            updateSecurityStatus('error', '❌', 'No camera/mic — manual mode');
            showStatus('No camera or microphone detected. You can still type answers.', 'error');
        }
    }

    // Always continue regardless of camera/mic outcome
    isInterviewActive = true;
    updateBotStatus('ready', 'Ready to start...');
}

async function uploadResume() {
    const apiKey = document.getElementById('apiKey').value.trim();
    const resumeFile = document.getElementById('resume').files[0];

    if (!apiKey || apiKey.length < 20) {
        showStatus('Please provide a valid API key', 'error');
        return;
    }

    if (!resumeFile) {
        showStatus('Please upload your resume', 'error');
        return;
    }

    const formData = new FormData();
    formData.append('api_key', apiKey);
    formData.append('resume', resumeFile);

    try {
        showStatus('Analyzing your resume...', 'info');
        const response = await fetch('/upload_resume', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.success) {
            sessionState = data.session_state;
            sessionId = sessionState.session_id;
            showStatus('Resume analyzed! Starting interview...', 'success');
            setTimeout(() => {
                showStep(2);
                initCamera();
                startInterview();
            }, 1500);
        } else {
            showStatus(data.error || 'Upload failed', 'error');
        }
    } catch (error) {
        showStatus('Error: ' + error.message, 'error');
    }
}

async function startInterview() {
    updateBotStatus('ready', 'Thinking...');
    
    try {
        const response = await fetch('/api/join_interview', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ session_state: sessionState })
        });
        
        const data = await response.json();
        
        if (response.ok && data.success) {
            sessionState = data.session_state;
            isProcessingResponse = false;
            addMessage('Interviewer', data.intro);
            currentQuestion = 0;
            totalQuestions = data.total_questions;
            updateProgress();
            
            const statusMsg = document.getElementById('statusMessage');
            if (statusMsg) statusMsg.classList.add('hidden');
            
            speakText(data.intro, true);
        } else {
            showStatus(data.error || 'Failed to start interview', 'error');
            updateBotStatus('ready', 'Failed to start');
        }
    } catch (error) {
        showStatus('API connection error: ' + error.message, 'error');
        updateBotStatus('ready', 'Connection failed');
    }
}

function speakText(text, autoListen = false) {
    synth.cancel();
    updateBotStatus('speaking', 'Speaking...');
    
    const utterance = new SpeechSynthesisUtterance(text);
    
    if (selectedVoice) {
        utterance.voice = selectedVoice;
    }
    utterance.rate = speechRate;
    
    utterance.onend = () => {
        updateBotStatus('ready', 'Ready');
        
        if (autoListen && isAutoMode && isInterviewActive && !isProcessingResponse) {
            if (isMicMuted) {
                // Do not auto-listen, set state and encourage user to type response
                isProcessingResponse = true;
                updateBotStatus('ready', 'Waiting for typed response...');
                const textInput = document.getElementById('textResponseInput');
                if (textInput) {
                    textInput.focus();
                }
            } else {
                setTimeout(() => {
                    if (!isProcessingResponse) {
                        startAutoResponse();
                    }
                }, 800);
            }
        }
    };
    
    synth.speak(utterance);
}

function startAutoResponse() {
    if (isProcessingResponse || !isInterviewActive) return;

    isProcessingResponse = true;
    accumulatedTranscript = '';
    clearTimeout(silenceTimeout);
    synth.cancel();
    updateBotStatus('listening', 'Listening...');
    
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        
        // Use continuous mode so recognition doesn't stop automatically when the user pauses briefly
        recognition.continuous = true;
        recognition.interimResults = false;
        recognition.lang = 'en-US';

        const recStatus = document.getElementById('recordingStatus');
        if (recStatus) recStatus.classList.remove('hidden');
        showStatus('Listening... Speak your answer now!', 'info');

        recognition.onresult = (event) => {
            let currentTranscript = '';
            for (let i = 0; i < event.results.length; ++i) {
                currentTranscript += event.results[i][0].transcript + ' ';
            }
            accumulatedTranscript = currentTranscript.trim();
            
            const liveTranscript = document.getElementById('liveTranscript');
            if (liveTranscript) liveTranscript.textContent = accumulatedTranscript;

            // Clear previous timeout and schedule a 5-second silence submission threshold
            clearTimeout(silenceTimeout);
            silenceTimeout = setTimeout(() => {
                console.log("Silence limit reached. Stopping speech recognition.");
                recognition.stop();
            }, 5000); // 5 seconds of silence before automatic cutoff and submission
        };

        recognition.onerror = (event) => {
            clearTimeout(silenceTimeout);
            if (recStatus) recStatus.classList.add('hidden');
            updateBotStatus('ready', 'Ready');
            
            if (event.error === 'no-speech') {
                showStatus('No speech detected. Restarting...', 'error');
                setTimeout(() => {
                    if (isAutoMode && isInterviewActive) {
                        isProcessingResponse = false;
                        startAutoResponse();
                    }
                }, 2000);
            } else {
                showStatus('Speech error. Restarting...', 'error');
                setTimeout(() => {
                    if (isAutoMode && isInterviewActive) {
                        isProcessingResponse = false;
                        startAutoResponse();
                    }
                }, 2000);
            }
        };

        recognition.onend = () => {
            clearTimeout(silenceTimeout);
            if (recStatus) recStatus.classList.add('hidden');
            
            if (accumulatedTranscript) {
                updateBotStatus('ready', 'Processing...');
                addMessage('Candidate', accumulatedTranscript);
                submitResponse(accumulatedTranscript);
            } else {
                updateBotStatus('ready', 'Ready');
                isProcessingResponse = false;
            }
        };

        try {
            recognition.start();
        } catch (error) {
            isProcessingResponse = false;
            showStatus('Error starting recognition', 'error');
        }
    } else {
        const response = prompt('Speech recognition not supported. Type response:');
        if (response && response.trim()) {
            addMessage('Candidate', response);
            submitResponse(response);
        } else {
            isProcessingResponse = false;
        }
        updateBotStatus('ready', 'Ready');
    }
}

async function submitResponse(response) {
    if (!sessionState || !response.trim()) {
        isProcessingResponse = false;
        return;
    }
    
    updateBotStatus('ready', 'Thinking...');
    
    try {
        const res = await fetch('/api/submit_response', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_state: sessionState,
                response: response.trim()
            })
        });
        
        const data = await res.json();
        
        if (!res.ok) {
            showStatus(data.error || 'Error submitting response', 'error');
            isProcessingResponse = false;
            updateBotStatus('ready', 'Ready');
            return;
        }
        
        sessionState = data.session_state;
        isProcessingResponse = false;
        
        const statusMsg = document.getElementById('statusMessage');
        if (statusMsg) statusMsg.classList.add('hidden');
        
        if (data.status === 'complete') {
            isInterviewActive = false;
            isAutoMode = false;
            clearInterval(faceCheckInterval);
            addMessage('Feedback', data.feedback);
            speakText('Interview complete. Please review your feedback.');
            setTimeout(() => {
                showFeedback(data.feedback);
                showStep(3);
            }, 3000);
        } else if (data.status === 'coding_challenge') {
            console.log('Coding challenge received');
            const challengeBox = document.getElementById('codingChallengeBox');
            if (challengeBox) {
                challengeBox.classList.remove('hidden');
                document.getElementById('codingLanguage').textContent = data.language || 'Python';
                document.getElementById('codingProblem').textContent = data.challenge;
                
                // Pre-fill code editor with function template
                const template = data.template || getDefaultTemplate(data.language);
                document.getElementById('codeEditor').value = template;
                
                document.getElementById('codeEvaluation').classList.add('hidden');
                challengeBox.scrollIntoView({ behavior: 'smooth' });
            }
            speakText('Please solve the coding challenge. Complete the function and submit when ready.', false);
        } else if (data.status === 'question') {
            addMessage('Interviewer', data.message);
            currentQuestion = data.question_number;
            totalQuestions = data.total_questions;
            updateProgress();
            speakText(data.message, true);
        }
    } catch (error) {
        showStatus('Connection error: ' + error.message, 'error');
        isProcessingResponse = false;
        updateBotStatus('ready', 'Ready');
    }
}

async function submitCode() {
    const code = document.getElementById('codeEditor').value.trim();
    
    if (!code) {
        alert('Please write some code before submitting!');
        return;
    }
    
    addMessage('Candidate', '[Code Submitted]');
    updateBotStatus('ready', 'Evaluating code...');
    
    try {
        const res = await fetch('/api/submit_code', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_state: sessionState,
                code: code
            })
        });
        
        const data = await res.json();
        
        if (!res.ok) {
            showStatus(data.error || 'Error evaluating code', 'error');
            updateBotStatus('ready', 'Evaluation failed');
            return;
        }
        
        sessionState = data.session_state;
        
        document.getElementById('correctnessScore').textContent = data.evaluation.correctness || data.evaluation.score;
        document.getElementById('qualityScore').textContent = data.evaluation.quality || data.evaluation.score;
        document.getElementById('efficiencyScore').textContent = data.evaluation.efficiency || data.evaluation.score;
        document.getElementById('codeFeedback').textContent = data.evaluation.feedback;
        
        const codeEval = document.getElementById('codeEvaluation');
        if (codeEval) codeEval.classList.remove('hidden');
        
        speakText('Code evaluated. Continuing with next question.', false);
        
        setTimeout(() => {
            const challengeBox = document.getElementById('codingChallengeBox');
            if (challengeBox) challengeBox.classList.add('hidden');
        }, 5000);
        
        setTimeout(() => {
            addMessage('Interviewer', data.next_question);
            currentQuestion = data.question_number;
            totalQuestions = data.total_questions;
            updateProgress();
            speakText(data.next_question, true);
        }, 2000);
        
    } catch (error) {
        showStatus('Connection error: ' + error.message, 'error');
        updateBotStatus('ready', 'Connection failed');
    }
}

function addMessage(role, content) {
    const chatBox = document.getElementById('chatBox');
    if (!chatBox) return;
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role.toLowerCase()}`;
    messageDiv.innerHTML = `<strong>${role}:</strong> ${content}`;
    chatBox.appendChild(messageDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function updateProgress() {
    const progressBar = document.getElementById('progressBar');
    if (progressBar) {
        const progress = (currentQuestion / totalQuestions) * 100;
        progressBar.style.width = progress + '%';
    }
}

function showStep(stepNumber) {
    document.querySelectorAll('.step').forEach(step => {
        step.classList.remove('active');
    });
    
    const stepEl = document.getElementById('step' + stepNumber);
    if (stepEl) stepEl.classList.add('active');

    if (stepNumber === 3) {
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
        }
        synth.cancel();
        isInterviewActive = false;
        isAutoMode = false;
        clearInterval(faceCheckInterval);
    }
    
    if (stepNumber === 2) {
        isProcessingResponse = false;
    }
}

// Global function to display errors/status banners
function showStatus(message, type) {
    const statusDiv = document.getElementById('statusMessage');
    if (!statusDiv) return;
    statusDiv.textContent = message;
    statusDiv.className = `status ${type}`;
    statusDiv.classList.remove('hidden');

    setTimeout(() => {
        statusDiv.classList.add('hidden');
    }, 5000);
}

function showFeedback(feedback) {
    const feedbackSec = document.getElementById('feedbackSection');
    if (feedbackSec) feedbackSec.textContent = feedback;
}

async function downloadReport() {
    if (!sessionState) {
        showStatus('No interview session active to download report', 'error');
        return;
    }
    try {
        showStatus('Generating PDF report...', 'info');
        const response = await fetch('/api/download_report', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ session_state: sessionState })
        });
        
        if (!response.ok) {
            throw new Error('Failed to generate report PDF');
        }
        
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `interview_report_${new Date().toISOString().slice(0,10)}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
        showStatus('Report downloaded successfully!', 'success');
    } catch (error) {
        showStatus('Error downloading report: ' + error.message, 'error');
    }
}

// Toggle microphone active/muted state
function toggleMic() {
    isMicMuted = !isMicMuted;
    const micBtn = document.getElementById('micToggleBtn');
    const textInput = document.getElementById('textResponseInput');
    
    if (isMicMuted) {
        micBtn.classList.add('muted');
        micBtn.querySelector('.icon').textContent = '🔇';
        micBtn.querySelector('.btn-text').textContent = 'Muted';
        showStatus('Microphone muted. Keyboard input enabled.', 'info');
        
        // Stop speech recognition immediately
        if (recognition) {
            try {
                recognition.stop();
            } catch (e) {}
        }
        clearTimeout(silenceTimeout);
        const recStatus = document.getElementById('recordingStatus');
        if (recStatus) recStatus.classList.add('hidden');
        
        if (isProcessingResponse) {
            updateBotStatus('ready', 'Waiting for typed response...');
        }
        if (textInput) textInput.focus();
    } else {
        micBtn.classList.remove('muted');
        micBtn.querySelector('.icon').textContent = '🎤';
        micBtn.querySelector('.btn-text').textContent = 'Active';
        showStatus('Microphone active. Auto-listening mode enabled.', 'success');
        
        // If waiting for user response, trigger auto-listen immediately
        if (isProcessingResponse && isInterviewActive) {
            isProcessingResponse = false;
            startAutoResponse();
        }
    }
}

// Submit a manually typed answer
function submitTypedResponse() {
    const textInput = document.getElementById('textResponseInput');
    if (!textInput) return;
    
    const responseText = textInput.value.trim();
    if (!responseText) return;
    
    // Clear the input field
    textInput.value = '';
    
    // Stop recording if active
    if (recognition) {
        try {
            recognition.stop();
        } catch (e) {}
    }
    clearTimeout(silenceTimeout);
    const recStatus = document.getElementById('recordingStatus');
    if (recStatus) recStatus.classList.add('hidden');
    
    addMessage('Candidate', responseText);
    
    isProcessingResponse = true;
    updateBotStatus('ready', 'Processing...');
    submitResponse(responseText);
}

// Bind Enter key in text input field
function handleInputKey(event) {
    if (event.key === 'Enter') {
        submitTypedResponse();
    }
}

window.addEventListener('beforeunload', () => {
    synth.cancel();
    if (stream) {
        stream.getTracks().forEach(track => track.stop());
    }
    clearInterval(faceCheckInterval);
});
