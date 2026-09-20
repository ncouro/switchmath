/**
 * Times Tables Quest - Frontend Application Logic
 * Supports: Delayed repetition quiz, Screen Time Bank,
 * Direct Nintendo Switch injection, and Live Diagnostics.
 */

let currentQuestion = null;
let questionStartTime = null;
let timerInterval = null;
let answerBuffer = "";
let isSubmitting = false;
let feedbackTimeout = null;
let logPollInterval = null;
let manualBankMode = "add"; // "add" or "deduct"

// DOM Elements - Quiz
const factorAEl = document.getElementById("factorA");
const factorBEl = document.getElementById("factorB");
const answerInput = document.getElementById("answerInput");
const answerDisplay = document.getElementById("answerDisplay");
const retryBadge = document.getElementById("retryBadge");
const questionTimerEl = document.getElementById("questionTimer");
const feedbackBanner = document.getElementById("feedbackBanner");
const feedbackIcon = document.getElementById("feedbackIcon");
const feedbackText = document.getElementById("feedbackText");

const rewardProgressBar = document.getElementById("rewardProgressBar");
const rewardProgressLabel = document.getElementById("rewardProgressLabel");
const todayEarnedMins = document.getElementById("todayEarnedMins");
const switchStatusBadge = document.getElementById("switchStatusBadge");
const switchStatusText = document.getElementById("switchStatusText");
const miniBankBalance = document.getElementById("miniBankBalance");
const bankHeroBalance = document.getElementById("bankHeroBalance");

// Switch Overview Elements
const overviewConsoleName = document.getElementById("overviewConsoleName");
const overviewRemaining = document.getElementById("overviewRemaining");
const overviewExtra = document.getElementById("overviewExtra");
const overviewPlayed = document.getElementById("overviewPlayed");
const overviewLimit = document.getElementById("overviewLimit");
const overviewBedtime = document.getElementById("overviewBedtime");
const resetExtraTimeBtn = document.getElementById("resetExtraTimeBtn");

// Modals
const celebrationModal = document.getElementById("celebrationModal");
const celebrationMessage = document.getElementById("celebrationMessage");
const celebrationSyncStatus = document.getElementById("celebrationSyncStatus");
const closeCelebrationBtn = document.getElementById("closeCelebrationBtn");

const manualBankModal = document.getElementById("manualBankModal");
const manualBankModalTitle = document.getElementById("manualBankModalTitle");
const manualBankInputLabel = document.getElementById("manualBankInputLabel");
const manualBankMinutesInput = document.getElementById("manualBankMinutesInput");
const manualBankReasonInput = document.getElementById("manualBankReasonInput");
const closeManualBankModalBtn = document.getElementById("closeManualBankModalBtn");
const confirmManualBankBtn = document.getElementById("confirmManualBankBtn");

const settingsModal = document.getElementById("settingsModal");
const openSettingsBtn = document.getElementById("openSettingsBtn");
const closeSettingsBtn = document.getElementById("closeSettingsBtn");
const saveSettingsBtn = document.getElementById("saveSettingsBtn");
const nintendoDetailText = document.getElementById("nintendoDetailText");
const deviceSelect = document.getElementById("deviceSelect");
const loginNintendoBtn = document.getElementById("loginNintendoBtn");
const settingRewardMode = document.getElementById("settingRewardMode");

const loginModal = document.getElementById("loginModal");
const closeLoginModalBtn = document.getElementById("closeLoginModalBtn");
const nintendoLoginLink = document.getElementById("nintendoLoginLink");
const callbackUrlInput = document.getElementById("callbackUrlInput");
const submitLoginCallbackBtn = document.getElementById("submitLoginCallbackBtn");

const masteryGrid = document.getElementById("masteryGrid");
const rewardsList = document.getElementById("rewardsList");

// Diagnostics Elements
const runDiagnosticBtn = document.getElementById("runDiagnosticBtn");
const diagnosticResults = document.getElementById("diagnosticResults");
const diagAuthStatus = document.getElementById("diagAuthStatus");
const diagTokenPreview = document.getElementById("diagTokenPreview");
const diagStepsBox = document.getElementById("diagStepsBox");
const boostResultBanner = document.getElementById("boostResultBanner");
const customBoostInput = document.getElementById("customBoostInput");
const customBoostBtn = document.getElementById("customBoostBtn");
const logConsole = document.getElementById("logConsole");
const refreshLogsBtn = document.getElementById("refreshLogsBtn");
const clearLogsBtn = document.getElementById("clearLogsBtn");

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupKeypad();
  setupManualBankUI();
  setupDiagnosticsUI();
  setupSettingsUI();
  refreshStatus();
  fetchNextQuestion();
});

// Tab Switching
function setupTabs() {
  const tabBtns = document.querySelectorAll(".tab-btn");
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      tabBtns.forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));

      btn.classList.add("active");
      const target = document.getElementById(btn.dataset.tab);
      if (target) target.classList.add("active");

      // Handle specific tab activations
      if (btn.dataset.tab === "bankTab") {
        refreshStatus();
        loadRewardsHistory();
      } else if (btn.dataset.tab === "matrixTab") {
        loadMasteryMatrix();
      } else if (btn.dataset.tab === "debugTab") {
        refreshStatus();
        loadDebugLogs();
        if (!logPollInterval) {
          logPollInterval = setInterval(loadDebugLogs, 4000);
        }
      } else if (btn.dataset.tab === "quizTab") {
        if (logPollInterval) {
          clearInterval(logPollInterval);
          logPollInterval = null;
        }
        if (answerInput) {
          setTimeout(() => answerInput.focus(), 50);
        }
      }
    });
  });
}

function switchToTab(tabId) {
  const tabBtn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
  if (tabBtn) tabBtn.click();
}

// Keypad & Keyboard Input
function setupKeypad() {
  document.querySelectorAll(".num-key").forEach(key => {
    key.addEventListener("click", () => {
      appendDigit(key.dataset.val);
      if (answerInput) answerInput.focus();
    });
  });

  const clearBtn = document.getElementById("clearBtn");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      if (feedbackTimeout) {
        clearTimeout(feedbackTimeout);
        feedbackTimeout = null;
        fetchNextQuestion();
      } else {
        clearAnswer();
        if (answerInput) answerInput.focus();
      }
    });
  }

  const submitBtn = document.getElementById("submitBtn");
  if (submitBtn) {
    submitBtn.addEventListener("click", () => {
      submitAnswer();
    });
  }

  // Bind input directly on the answer input box
  if (answerInput) {
    answerInput.addEventListener("input", () => {
      if (feedbackTimeout) {
        clearTimeout(feedbackTimeout);
        feedbackTimeout = null;
      }
      const sanitized = answerInput.value.replace(/[^0-9]/g, "").slice(0, 4);
      answerInput.value = sanitized;
      answerBuffer = sanitized;
      updateAnswerDisplay();
    });

    answerInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === "NumpadEnter") {
        e.preventDefault();
        submitAnswer();
      } else if (e.key === "Escape") {
        e.preventDefault();
        clearAnswer();
      }
    });

    answerInput.addEventListener("focus", () => {
      answerInput.select();
    });

    answerInput.addEventListener("click", () => {
      if (feedbackTimeout) {
        clearTimeout(feedbackTimeout);
        feedbackTimeout = null;
        fetchNextQuestion();
      } else {
        answerInput.select();
      }
    });

    // When user clicks anywhere on the equation card, focus or advance
    const qDisplay = document.querySelector(".question-display");
    if (qDisplay) {
      qDisplay.addEventListener("click", () => {
        if (feedbackTimeout) {
          clearTimeout(feedbackTimeout);
          feedbackTimeout = null;
          fetchNextQuestion();
        } else if (answerInput) {
          answerInput.focus();
        }
      });
    }
  }

  window.addEventListener("keydown", (e) => {
    // If typing inside settings or modals, ignore
    if (e.target.tagName === "INPUT" && e.target.id !== "answerInput") return;
    if (e.target.tagName === "SELECT" || e.target.tagName === "TEXTAREA") return;

    // If feedback is showing, any key immediately advances
    if (feedbackTimeout) {
      if (e.key === "Enter" || e.key === "NumpadEnter" || e.key === " " || e.key === "Escape") {
        e.preventDefault();
        clearTimeout(feedbackTimeout);
        feedbackTimeout = null;
        fetchNextQuestion();
        return;
      } else if (e.key >= "0" && e.key <= "9") {
        e.preventDefault();
        clearTimeout(feedbackTimeout);
        feedbackTimeout = null;
        fetchNextQuestion(e.key);
        return;
      }
    }

    if (e.target.id !== "answerInput") {
      if (e.key >= "0" && e.key <= "9") {
        appendDigit(e.key);
        if (answerInput) answerInput.focus();
      } else if (e.key === "Backspace") {
        backspace();
        if (answerInput) answerInput.focus();
      } else if (e.key === "Enter" || e.key === "NumpadEnter") {
        submitAnswer();
      } else if (e.key === "Escape") {
        clearAnswer();
        if (answerInput) answerInput.focus();
      }
    }
  });
}

function appendDigit(digit) {
  if (feedbackTimeout) {
    clearTimeout(feedbackTimeout);
    feedbackTimeout = null;
    fetchNextQuestion(digit);
    return;
  }
  if (isSubmitting) return;
  if (answerBuffer.length >= 4) return;
  answerBuffer += digit;
  updateAnswerDisplay();
}

function backspace() {
  if (feedbackTimeout) {
    clearTimeout(feedbackTimeout);
    feedbackTimeout = null;
    fetchNextQuestion();
    return;
  }
  if (isSubmitting) return;
  answerBuffer = answerBuffer.slice(0, -1);
  updateAnswerDisplay();
}

function clearAnswer() {
  answerBuffer = "";
  if (answerInput) {
    answerInput.value = "";
    answerInput.classList.remove("active", "correct", "wrong");
  }
  updateAnswerDisplay();
}

function updateAnswerDisplay() {
  if (answerInput) {
    answerInput.value = answerBuffer;
    if (answerBuffer) {
      answerInput.classList.add("active");
    } else {
      answerInput.classList.remove("active");
    }
  }
  if (answerDisplay) {
    if (answerBuffer) {
      answerDisplay.textContent = answerBuffer;
      answerDisplay.classList.add("active");
    } else {
      answerDisplay.textContent = "?";
      answerDisplay.classList.remove("active");
    }
  }
}

// Timer
function startTimer() {
  if (timerInterval) clearInterval(timerInterval);
  questionStartTime = performance.now();
  questionTimerEl.textContent = "0.0s";

  timerInterval = setInterval(() => {
    const elapsed = (performance.now() - questionStartTime) / 1000;
    questionTimerEl.textContent = elapsed.toFixed(1) + "s";
  }, 100);
}

function stopTimer() {
  if (timerInterval) clearInterval(timerInterval);
  return performance.now() - questionStartTime;
}

// Quiz Flow
async function fetchNextQuestion(prefillDigit = null) {
  if (feedbackTimeout) {
    clearTimeout(feedbackTimeout);
    feedbackTimeout = null;
  }
  isSubmitting = false;
  hideFeedback();
  clearAnswer();

  if (answerInput) {
    answerInput.readOnly = false;
    answerInput.disabled = false;
    answerInput.value = "";
    answerInput.classList.remove("active", "correct", "wrong");
  }

  try {
    const res = await fetch("/api/quiz/next");
    const data = await res.json();
    currentQuestion = data;

    factorAEl.textContent = data.factor_a;
    factorBEl.textContent = data.factor_b;

    if (data.is_retry) {
      retryBadge.classList.remove("hidden");
      retryBadge.textContent = data.prompt_reason.includes("slow")
        ? "⚡ Speed Practice"
        : "🔁 Delayed Review";
    } else {
      retryBadge.classList.add("hidden");
    }

    startTimer();

    if (prefillDigit !== null && prefillDigit !== undefined) {
      appendDigit(prefillDigit);
    }

    if (answerInput) {
      answerInput.focus();
      answerInput.select();
    }
  } catch (err) {
    console.error("Failed to load next question", err);
    isSubmitting = false;
    if (answerInput) answerInput.readOnly = false;
  }
}

async function submitAnswer() {
  if (feedbackTimeout) {
    clearTimeout(feedbackTimeout);
    feedbackTimeout = null;
    await fetchNextQuestion();
    return;
  }

  if (isSubmitting || !currentQuestion) return;

  if (answerBuffer.trim() === "") {
    if (answerInput) {
      answerInput.classList.add("wrong");
      setTimeout(() => answerInput.classList.remove("wrong"), 300);
      answerInput.focus();
    }
    return;
  }

  isSubmitting = true;
  if (answerInput) {
    answerInput.readOnly = true;
  }

  const latencyMs = stopTimer();
  const userAnswer = parseInt(answerBuffer, 10);

  try {
    const res = await fetch("/api/quiz/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        factor_a: currentQuestion.factor_a,
        factor_b: currentQuestion.factor_b,
        user_answer: userAnswer,
        latency_ms: latencyMs,
      }),
    });

    if (!res.ok) {
      throw new Error(`Submit failed with HTTP ${res.status}`);
    }

    const data = await res.json();
    showFeedback(data.evaluation);
    updateRewardProgress(data);

    if (answerInput) {
      if (data.evaluation && data.evaluation.is_correct) {
        answerInput.classList.add("correct");
      } else {
        answerInput.classList.add("wrong");
      }
    }

    if (data.reward_earned && data.reward_info) {
      triggerCelebration(data.reward_info);
    }

    const delay = (data.evaluation && data.evaluation.is_correct) ? 750 : 2000;
    feedbackTimeout = setTimeout(() => {
      fetchNextQuestion();
    }, delay);

  } catch (err) {
    console.error("Error submitting answer", err);
    isSubmitting = false;
    if (answerInput) {
      answerInput.readOnly = false;
      answerInput.focus();
    }
  }
}

function showFeedback(evaluation) {
  feedbackBanner.className = `feedback-banner ${evaluation.evaluation}`;
  feedbackBanner.classList.remove("hidden");

  if (evaluation.evaluation === "fast") {
    feedbackIcon.textContent = "⚡";
    feedbackText.textContent = evaluation.message;
  } else if (evaluation.evaluation === "slow") {
    feedbackIcon.textContent = "👍";
    feedbackText.textContent = evaluation.message;
  } else {
    feedbackIcon.textContent = "💡";
    feedbackText.textContent = evaluation.message;
  }
}

function hideFeedback() {
  feedbackBanner.classList.add("hidden");
}

function updateRewardProgress(data) {
  const current = data.progress_to_next !== undefined ? data.progress_to_next : (data.rewards ? data.rewards.progress_to_next_reward : 0);
  const total = data.questions_per_reward || (data.rewards ? data.rewards.questions_per_reward : 15);
  const mins = data.minutes_per_reward || (data.rewards ? data.rewards.minutes_per_reward : 5);
  const percent = Math.min(100, Math.round((current / total) * 100));

  if (rewardProgressBar) rewardProgressBar.style.width = `${percent}%`;
  if (rewardProgressLabel) rewardProgressLabel.textContent = `${current} / ${total} to +${mins} Min Switch Reward`;
}

// Audio Synthesis for cute chimes & coins
function playCuteSound(type) {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    if (ctx.state === "suspended") ctx.resume();
    const now = ctx.currentTime;

    if (type === "redeem") {
      // Cheerful triumphant chime (C5 -> E5 -> G5 -> C6)
      const notes = [523.25, 659.25, 783.99, 1046.50];
      notes.forEach((freq, idx) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "triangle";
        osc.frequency.setValueAtTime(freq, now + idx * 0.08);
        gain.gain.setValueAtTime(0, now + idx * 0.08);
        gain.gain.linearRampToValueAtTime(0.2, now + idx * 0.08 + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.08 + 0.35);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now + idx * 0.08);
        osc.stop(now + idx * 0.08 + 0.38);
      });
    } else if (type === "coin") {
      // High bell ding for coin deposit
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(987.77, now);
      osc.frequency.exponentialRampToValueAtTime(1318.51, now + 0.08);
      gain.gain.setValueAtTime(0.22, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.35);
    }
  } catch (e) {
    // Ignore audio restrictions gracefully
  }
}

let isMascotAnimating = false;

function triggerMascotRedeemAnimation(minutes, deviceName) {
  isMascotAnimating = true;
  playCuteSound("redeem");

  const piggyWrapper = document.getElementById("piggyWrapper");
  const portal = document.getElementById("flyingCoinPortal");
  const normalEyes = document.getElementById("piggyNormalEyes");
  const happyEyes = document.getElementById("piggyHappyEyes");
  const switchTarget = document.getElementById("switchTargetBadge");
  const bubbleText = document.getElementById("piggyBubbleText");

  if (piggyWrapper) {
    piggyWrapper.classList.remove("piggy-jump", "piggy-wiggle", "piggy-shake");
    void piggyWrapper.offsetWidth; // trigger reflow
    piggyWrapper.classList.add("piggy-wiggle");
  }

  if (normalEyes && happyEyes) {
    normalEyes.classList.add("hidden");
    happyEyes.classList.remove("hidden");
  }

  if (portal) {
    portal.classList.remove("hidden");
    portal.classList.remove("animating");
    void portal.offsetWidth;
    portal.classList.add("animating");
  }

  if (switchTarget) {
    switchTarget.classList.add("active-glow");
  }

  if (bubbleText) {
    bubbleText.textContent = `Yay! Redeemed +${minutes}m to ${deviceName || "Switch"}! 🎮✨`;
  }

  if (window.confetti) {
    confetti({
      particleCount: 70,
      spread: 65,
      origin: { y: 0.55 },
    });
  }

  setTimeout(() => {
    if (portal) {
      portal.classList.remove("animating");
      portal.classList.add("hidden");
    }
    if (switchTarget) {
      switchTarget.classList.remove("active-glow");
    }
    if (piggyWrapper) {
      piggyWrapper.classList.remove("piggy-wiggle");
    }
    if (normalEyes && happyEyes) {
      normalEyes.classList.remove("hidden");
      happyEyes.classList.add("hidden");
    }
    isMascotAnimating = false;
    const heroEl = document.getElementById("bankHeroBalance");
    const current = heroEl ? (parseInt(heroEl.textContent, 10) || 0) : 0;
    updateBankBalances(current);
  }, 2400);
}

function triggerMascotDepositAnimation(minutes) {
  playCuteSound("coin");
  const piggyWrapper = document.getElementById("piggyWrapper");
  const bubbleText = document.getElementById("piggyBubbleText");
  const normalEyes = document.getElementById("piggyNormalEyes");
  const happyEyes = document.getElementById("piggyHappyEyes");

  if (piggyWrapper) {
    piggyWrapper.classList.remove("piggy-jump", "piggy-wiggle", "piggy-shake");
    void piggyWrapper.offsetWidth;
    piggyWrapper.classList.add("piggy-jump");
  }
  if (normalEyes && happyEyes) {
    normalEyes.classList.add("hidden");
    happyEyes.classList.remove("hidden");
  }
  if (bubbleText) {
    bubbleText.textContent = `Yum! +${minutes}m deposited into the bank! 🪙😋`;
  }

  setTimeout(() => {
    if (piggyWrapper) piggyWrapper.classList.remove("piggy-jump");
    if (normalEyes && happyEyes) {
      normalEyes.classList.remove("hidden");
      happyEyes.classList.add("hidden");
    }
    const heroEl = document.getElementById("bankHeroBalance");
    const current = heroEl ? (parseInt(heroEl.textContent, 10) || 0) : 0;
    updateBankBalances(current);
  }, 1800);
}

function triggerMascotShake() {
  const piggyWrapper = document.getElementById("piggyWrapper");
  const bubbleText = document.getElementById("piggyBubbleText");

  if (piggyWrapper) {
    piggyWrapper.classList.remove("piggy-jump", "piggy-wiggle", "piggy-shake");
    void piggyWrapper.offsetWidth;
    piggyWrapper.classList.add("piggy-shake");
  }
  if (bubbleText) {
    bubbleText.textContent = "Bank is empty! Practice quiz questions to earn time! 🎯";
  }
  setTimeout(() => {
    if (piggyWrapper) piggyWrapper.classList.remove("piggy-shake");
  }, 600);
}

function updateBankBalances(balance) {
  const b = (balance !== undefined && balance !== null) ? balance : 0;
  const navBank = document.getElementById("navBankBalance");
  if (navBank) navBank.textContent = b;
  const miniBank = document.getElementById("miniBankBalance");
  if (miniBank) miniBank.textContent = b;
  const heroBank = document.getElementById("bankHeroBalance");
  if (heroBank) heroBank.textContent = b;

  // Update Primary Redeem Button state & label
  const mainRedeemBtn = document.getElementById("mainRedeemBtn");
  const mainRedeemLabel = document.getElementById("mainRedeemLabel");
  const mainRedeemSub = document.getElementById("mainRedeemSub");
  const bubbleText = document.getElementById("piggyBubbleText");

  if (mainRedeemBtn && mainRedeemLabel && mainRedeemSub) {
    if (b > 0) {
      const quickMins = Math.min(5, b);
      mainRedeemBtn.classList.remove("disabled");
      mainRedeemLabel.textContent = `Redeem ${quickMins}m to Switch`;
      mainRedeemSub.textContent = `Instant Playtime on Console 🎮`;
    } else {
      mainRedeemBtn.classList.add("disabled");
      mainRedeemLabel.textContent = "Redeem to Switch";
      mainRedeemSub.textContent = "Bank is empty (earn in Quiz) 🎯";
    }
  }

  if (!isMascotAnimating && bubbleText) {
    if (b > 0) {
      bubbleText.textContent = `I'm holding ${b} minutes for your Switch! 🎮 Tap Redeem!`;
    } else {
      bubbleText.textContent = "Feed me times tables to earn minutes! 🪙";
    }
  }
}

function triggerCelebration(rewardInfo) {
  playCuteSound("coin");
  celebrationMessage.textContent = rewardInfo.message || `You earned +${rewardInfo.minutes || 5} minutes! 🎮`;
  celebrationSyncStatus.textContent = rewardInfo.synced
    ? `✓ Successfully added to ${rewardInfo.device_name || "your Switch"}!`
    : (rewardInfo.message || "✓ Saved to your Time Bank!");

  celebrationModal.classList.remove("hidden");

  if (window.confetti) {
    confetti({
      particleCount: 80,
      spread: 70,
      origin: { y: 0.6 },
    });
  }

  // If time was deposited to bank, animate mascot eating coin
  if (!rewardInfo.synced) {
    triggerMascotDepositAnimation(rewardInfo.minutes || 5);
  }

  refreshStatus();
}

closeCelebrationBtn.addEventListener("click", () => {
  celebrationModal.classList.add("hidden");
  fetchNextQuestion();
});

// Screen Time Bank & Manual Controls
function setupManualBankUI() {
  const quickAddBtn = document.getElementById("quickAddBankBtn");
  const quickWithdrawBtn = document.getElementById("quickWithdrawBtn");
  const openAddBtn = document.getElementById("openManualAddModalBtn");
  const openDeductBtn = document.getElementById("openManualDeductModalBtn");
  const resetBankBtn = document.getElementById("resetBankBtn");

  if (quickWithdrawBtn) {
    quickWithdrawBtn.addEventListener("click", () => switchToTab("bankTab"));
  }

  const openModal = (mode) => {
    manualBankMode = mode;
    if (mode === "add") {
      manualBankModalTitle.textContent = "➕ Add Time Manually";
      manualBankInputLabel.textContent = "Minutes to add to Bank:";
      manualBankMinutesInput.value = 10;
      manualBankReasonInput.value = "Math practice bonus";
    } else {
      manualBankModalTitle.textContent = "➖ Deduct / Redeem Time";
      manualBankInputLabel.textContent = "Minutes to deduct from Bank:";
      manualBankMinutesInput.value = 10;
      manualBankReasonInput.value = "Redeemed for screen time";
    }
    manualBankModal.classList.remove("hidden");
  };

  if (quickAddBtn) quickAddBtn.addEventListener("click", () => openModal("add"));
  if (openAddBtn) openAddBtn.addEventListener("click", () => openModal("add"));
  if (openDeductBtn) openDeductBtn.addEventListener("click", () => openModal("deduct"));

  if (resetBankBtn) {
    resetBankBtn.addEventListener("click", performResetBank);
  }

  closeManualBankModalBtn.addEventListener("click", () => {
    manualBankModal.classList.add("hidden");
  });

  confirmManualBankBtn.addEventListener("click", async () => {
    const mins = parseInt(manualBankMinutesInput.value, 10);
    const reason = manualBankReasonInput.value.trim() || "Manual adjustment";

    if (isNaN(mins) || mins <= 0) {
      alert("Please enter a valid number of minutes.");
      return;
    }

    const delta = (manualBankMode === "add") ? mins : -mins;

    try {
      const res = await fetch("/api/bank/adjust", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ minutes: delta, reason }),
      });
      const data = await res.json();
      if (res.ok) {
        updateBankBalances(data.new_balance);
        manualBankModal.classList.add("hidden");
        refreshStatus();
        loadRewardsHistory();
      } else {
        alert(data.detail || "Failed to adjust bank.");
      }
    } catch (err) {
      alert("Error: " + err);
    }
  });

  // Primary Redeem to Switch button
  const mainRedeemBtn = document.getElementById("mainRedeemBtn");
  if (mainRedeemBtn) {
    mainRedeemBtn.addEventListener("click", () => {
      const heroEl = document.getElementById("bankHeroBalance");
      const currentBank = heroEl ? (parseInt(heroEl.textContent, 10) || 0) : 0;
      if (currentBank <= 0) {
        triggerMascotShake();
        alert("Your Time Bank is empty! Practice questions in the Quiz to earn screen time minutes first! 🎯");
        return;
      }
      const minsToRedeem = Math.min(5, currentBank);
      performBankWithdraw(minsToRedeem);
    });
  }

  // Interactive Piggy Mascot click
  const piggyWrapper = document.getElementById("piggyWrapper");
  if (piggyWrapper) {
    piggyWrapper.addEventListener("click", () => {
      const heroEl = document.getElementById("bankHeroBalance");
      const currentBank = heroEl ? (parseInt(heroEl.textContent, 10) || 0) : 0;
      piggyWrapper.classList.remove("piggy-jump");
      void piggyWrapper.offsetWidth;
      piggyWrapper.classList.add("piggy-jump");
      playCuteSound("coin");
      const bubbleText = document.getElementById("piggyBubbleText");
      if (bubbleText) {
        bubbleText.textContent = currentBank > 0
          ? `Oink! Tap 'Redeem' to send ${Math.min(5, currentBank)}m to your Switch! 🎮`
          : "Oink! Feed me times tables to earn minutes! ⭐";
      }
      setTimeout(() => {
        piggyWrapper.classList.remove("piggy-jump");
      }, 700);
    });
  }

  // Quick withdraw buttons in Bank Tab (+5, +10, +15, +30, All)
  document.querySelectorAll(".withdraw-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const heroEl = document.getElementById("bankHeroBalance");
      const currentBank = heroEl ? (parseInt(heroEl.textContent, 10) || 0) : 0;
      if (currentBank <= 0) {
        triggerMascotShake();
        alert("Your Time Bank is empty. Practice questions or add time first!");
        return;
      }

      if (btn.id === "withdrawAllBtn") {
        performBankWithdraw(currentBank);
        return;
      }

      const mins = parseInt(btn.dataset.mins, 10);
      if (isNaN(mins) || mins <= 0) return;
      if (mins > currentBank) {
        triggerMascotShake();
        alert(`You only have ${currentBank} minutes in your Bank. You cannot redeem ${mins} minutes.`);
        return;
      }
      performBankWithdraw(mins);
    });
  });

  // Custom withdraw button in Bank Tab
  const customWithdrawBtn = document.getElementById("customWithdrawBtn");
  const customWithdrawInput = document.getElementById("customWithdrawInput");
  if (customWithdrawBtn) {
    customWithdrawBtn.addEventListener("click", () => {
      const heroEl = document.getElementById("bankHeroBalance");
      const currentBank = heroEl ? (parseInt(heroEl.textContent, 10) || 0) : 0;
      if (currentBank <= 0) {
        triggerMascotShake();
        alert("Your Time Bank is empty. Practice questions or add time first!");
        return;
      }

      const mins = parseInt(customWithdrawInput.value, 10);
      if (isNaN(mins) || mins <= 0) {
        alert("Please enter a valid number of minutes to redeem.");
        return;
      }
      if (mins > currentBank) {
        triggerMascotShake();
        alert(`Requested ${mins}m exceeds current Bank balance (${currentBank}m).`);
        return;
      }
      performBankWithdraw(mins);
    });
  }
}

async function performBankWithdraw(minutes) {
  const banner = document.getElementById("withdrawStatusBanner");
  if (banner) {
    banner.className = "withdraw-status-banner";
    banner.textContent = `Redeeming +${minutes}m to Nintendo Switch...`;
    banner.classList.remove("hidden");
  }

  try {
    const res = await fetch("/api/bank/withdraw", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ minutes }),
    });
    const data = await res.json();
    if (res.ok) {
      if (banner) {
        banner.className = "withdraw-status-banner success";
        banner.textContent = `✓ Successfully redeemed +${minutes} minutes to ${data.device_name || "Switch"}!`;
      }
      updateBankBalances(data.new_bank_balance);
      triggerMascotRedeemAnimation(minutes, data.device_name);
      triggerCelebration({
        minutes: minutes,
        synced: true,
        device_name: data.device_name,
        message: `Redeemed +${minutes}m from Bank to ${data.device_name || "Switch"}! 🎮✨`,
      });
      await refreshStatus();
      loadRewardsHistory();
    } else {
      triggerMascotShake();
      if (banner) {
        banner.className = "withdraw-status-banner error";
        banner.textContent = `✕ Transfer failed: ${data.detail || "Switch error"}. (Minutes remain in bank)`;
      }
      alert(`Transfer failed: ${data.detail || "Could not sync with Switch."}\n(Minutes remain safe in your bank)`);
    }
  } catch (err) {
    triggerMascotShake();
    if (banner) {
      banner.className = "withdraw-status-banner error";
      banner.textContent = `✕ Error: ${err}`;
    }
    alert("Error syncing to Switch: " + err);
  }
}

async function performResetBank() {
  if (!confirm("Reset your Screen Time Bank balance to 0 minutes?")) return;
  try {
    const res = await fetch("/api/bank/reset", { method: "POST" });
    const data = await res.json();
    updateBankBalances(0);
    alert(data.message || "Time Bank balance has been reset to 0.");
    await refreshStatus();
    loadRewardsHistory();
  } catch (err) {
    alert("Failed to reset bank: " + err);
  }
}

// Diagnostics & Debug UI
function setupDiagnosticsUI() {
  // 1. Run Diagnostic Button
  if (runDiagnosticBtn) {
    runDiagnosticBtn.addEventListener("click", async () => {
      runDiagnosticBtn.disabled = true;
      runDiagnosticBtn.textContent = "Running diagnostics...";
      diagnosticResults.classList.remove("hidden");
      diagAuthStatus.textContent = "Running tests...";
      diagStepsBox.textContent = "Starting diagnostic probe...\n";

      try {
        const res = await fetch("/api/debug/test-nintendo", { method: "POST" });
        const data = await res.json();

        diagAuthStatus.textContent = data.auth_status;
        diagAuthStatus.style.color = data.auth_status === "CONNECTED" ? "#10b981" : "#ef4444";
        diagTokenPreview.textContent = data.token_preview || "None found";

        let logOutput = (data.steps || []).join("\n");
        if (data.error) {
          logOutput += `\n\n[ERROR DETAILS]: ${data.error}`;
        }
        if (data.devices && data.devices.length > 0) {
          logOutput += "\n\n[DETECTED CONSOLES]:\n" + JSON.stringify(data.devices, null, 2);
        }
        diagStepsBox.textContent = logOutput;
        refreshStatus();
      } catch (err) {
        diagStepsBox.textContent += `\nNetwork error: ${err}`;
      } finally {
        runDiagnosticBtn.disabled = false;
        runDiagnosticBtn.textContent = "▶ Run Diagnostic Check";
      }
    });
  }

  // 2. Direct Boost Buttons
  document.querySelectorAll(".boost-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      injectManualTime(parseInt(btn.dataset.mins, 10));
    });
  });

  if (customBoostBtn) {
    customBoostBtn.addEventListener("click", () => {
      const val = parseInt(customBoostInput.value, 10);
      if (isNaN(val) || val <= 0) {
        alert("Please enter a valid number of minutes.");
        return;
      }
      injectManualTime(val);
    });
  }

  // 3. Log Console actions
  if (refreshLogsBtn) refreshLogsBtn.addEventListener("click", loadDebugLogs);
  if (clearLogsBtn) {
    clearLogsBtn.addEventListener("click", async () => {
      await fetch("/api/debug/logs", { method: "DELETE" });
      logConsole.innerHTML = '<div class="log-entry">Logs cleared.</div>';
    });
  }

  // 4. Reset Extra Time action
  if (resetExtraTimeBtn) {
    resetExtraTimeBtn.addEventListener("click", async () => {
      if (!confirm("Reset extra playtime on the Nintendo Switch console back to 0?")) return;
      resetExtraTimeBtn.textContent = "Resetting...";
      try {
        const res = await fetch("/api/nintendo/cancel-extra-time", { method: "POST" });
        const data = await res.json();
        alert(data.message || "Extra playtime reset to 0.");
        await refreshStatus();
        loadDebugLogs();
      } catch (err) {
        alert("Failed to reset extra time: " + err);
      } finally {
        resetExtraTimeBtn.textContent = "🔄 Reset Extra Time to 0";
      }
    });
  }

  // 5. Reset Today's Allowance action
  const resetTodayAllowanceBtn = document.getElementById("resetTodayAllowanceBtn");
  if (resetTodayAllowanceBtn) {
    resetTodayAllowanceBtn.addEventListener("click", performResetTodayAllowance);
  }

  const resetAllowanceHeaderBtn = document.getElementById("resetAllowanceHeaderBtn");
  if (resetAllowanceHeaderBtn) {
    resetAllowanceHeaderBtn.addEventListener("click", performResetTodayAllowance);
  }
}

async function performResetTodayAllowance() {
  if (!confirm("Reset today's reward allowance and Switch bonus time back to 0 for a fresh start?")) return;
  try {
    const res = await fetch("/api/allowance/reset-today", { method: "POST" });
    const data = await res.json();
    alert(data.message || "Today's allowance has been reset.");
    await refreshStatus();
    loadMasteryMatrix();
    loadRewardsHistory();
    loadDebugLogs();
  } catch (err) {
    alert("Failed to reset allowance: " + err);
  }
}

async function injectManualTime(minutes) {
  boostResultBanner.className = "boost-result-banner hidden";
  boostResultBanner.textContent = `Sending +${minutes} minutes to Nintendo Switch...`;
  boostResultBanner.classList.remove("hidden");

  try {
    const res = await fetch("/api/nintendo/add-time-manual", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ minutes }),
    });
    const data = await res.json();

    if (res.ok && data.success) {
      boostResultBanner.className = "boost-result-banner success";
      boostResultBanner.textContent = `✓ Success! Added +${minutes} mins to ${data.device_name}. Extra is now: ${data.extra_playing_time}m, remaining: ${data.today_time_remaining}m.`;
      refreshStatus();
      loadDebugLogs();
      loadRewardsHistory();
    } else {
      boostResultBanner.className = "boost-result-banner error";
      boostResultBanner.textContent = `✕ Error: ${data.detail || data.message || "Request failed"}`;
    }
  } catch (err) {
    boostResultBanner.className = "boost-result-banner error";
    boostResultBanner.textContent = `✕ Network error: ${err}`;
  }
}

async function loadDebugLogs() {
  if (!logConsole) return;
  try {
    const res = await fetch("/api/debug/logs");
    const data = await res.json();
    if (!data.logs || data.logs.length === 0) {
      logConsole.innerHTML = '<div class="log-entry">No Nintendo API activity logged yet.</div>';
      return;
    }

    // Filter to focus on Nintendo API requests, responses, and updates
    const relevantLogs = data.logs.filter(log => {
      const msg = log.message || "";
      return msg.includes("Nintendo API") ||
             msg.includes("POST") ||
             msg.includes("status=") ||
             msg.includes("extra is now") ||
             msg.includes("playtime updated") ||
             log.level === "ERROR" ||
             log.logger === "app.nintendo" ||
             log.logger === "nintendo.api";
    });

    const displayList = relevantLogs.length > 0 ? relevantLogs : data.logs;

    logConsole.innerHTML = displayList.map(log => {
      return `<div class="log-entry ${log.level}">
        <span class="log-time">[${log.timestamp.split(" ")[1]}]</span>
        <span class="log-lvl">[${log.level}]</span>
        <span class="log-msg">${escapeHtml(log.message)}</span>
      </div>`;
    }).join("");

    // Auto-scroll to bottom
    logConsole.scrollTop = logConsole.scrollHeight;
  } catch (err) {
    console.error("Failed to load logs", err);
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// Status & Nintendo Info
async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();

    const dot = switchStatusBadge.querySelector(".status-dot");
    const dev = (data.devices && data.devices.length > 0)
      ? (data.devices.find(d => d.device_id === data.selected_device_id) || data.devices[0])
      : null;

    if (data.nintendo_connected && dev) {
      dot.className = "status-dot connected";
      const name = dev.name || "Switch";
      const rem = dev.today_time_remaining !== undefined ? dev.today_time_remaining : "?";
      switchStatusText.textContent = `${name}: ${rem}m left`;

      // Update Overview Card in Controls tab
      if (overviewConsoleName) overviewConsoleName.textContent = dev.name || "Switch";
      if (overviewRemaining) overviewRemaining.textContent = `${dev.today_time_remaining} min`;
      if (overviewExtra) overviewExtra.textContent = `${dev.extra_playing_time || 0} min`;
      if (overviewPlayed) overviewPlayed.textContent = `${dev.today_playing_time || 0} min`;
      if (overviewLimit) overviewLimit.textContent = `${dev.limit_time || 0} min`;
      if (overviewBedtime) overviewBedtime.textContent = dev.bedtime_alarm || "None";
    } else if (data.nintendo_connected) {
      dot.className = "status-dot connected";
      switchStatusText.textContent = "Switch: Connected";
    } else {
      dot.className = "status-dot disconnected";
      switchStatusText.textContent = "Switch: Not Connected";
      if (overviewRemaining) overviewRemaining.textContent = "Not connected";
    }

    if (todayEarnedMins) todayEarnedMins.textContent = data.rewards.today_rewarded_minutes;
    updateBankBalances(data.rewards.bank_balance);

    updateRewardProgress({
      progress_to_next: data.rewards.progress_to_next_reward,
      questions_per_reward: data.rewards.questions_per_reward,
      minutes_per_reward: data.rewards.minutes_per_reward,
    });
  } catch (err) {
    console.error("Failed to refresh status", err);
  }
}

// Mastery Matrix
async function loadMasteryMatrix() {
  try {
    const res = await fetch("/api/stats");
    const data = await res.json();

    masteryGrid.innerHTML = "";

    // Empty corner
    const corner = document.createElement("div");
    corner.className = "cell header-cell";
    corner.textContent = "×";
    masteryGrid.appendChild(corner);

    // Column headers (2..12)
    for (let b = 2; b <= 12; b++) {
      const colHeader = document.createElement("div");
      colHeader.className = "cell header-cell";
      colHeader.textContent = b;
      masteryGrid.appendChild(colHeader);
    }

    // Rows
    data.matrix.forEach(row => {
      const rowHeader = document.createElement("div");
      rowHeader.className = "cell header-cell";
      rowHeader.textContent = row.factor;
      masteryGrid.appendChild(rowHeader);

      row.facts.forEach(fact => {
        const cell = document.createElement("div");
        const isExcluded = fact.is_active === false;
        cell.className = `cell ${fact.status}${isExcluded ? " excluded-cell" : ""}`;
        cell.textContent = fact.product;
        const latencySec = (fact.avg_latency_ms / 1000).toFixed(1);
        const excludedNote = isExcluded ? " [Excluded from practice]" : "";
        cell.title = `${fact.a} × ${fact.b} = ${fact.product}${excludedNote}\nStatus: ${fact.status}\nBox: ${fact.box}/5\nAvg Speed: ${latencySec}s\nAttempts: ${fact.attempts}`;
        masteryGrid.appendChild(cell);
      });
    });
  } catch (err) {
    console.error("Failed to load matrix", err);
  }
}

// Rewards History
async function loadRewardsHistory() {
  try {
    const res = await fetch("/api/stats");
    const data = await res.json();

    if (!data.recent_rewards || data.recent_rewards.length === 0) {
      rewardsList.innerHTML = '<div class="empty-state">No rewards logged yet today. Start answering questions!</div>';
      return;
    }

    rewardsList.innerHTML = "";
    data.recent_rewards.forEach(r => {
      const item = document.createElement("div");
      item.className = `reward-item ${r.synced_to_switch ? "synced" : ""}`;
      const timeStr = new Date(r.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      item.innerHTML = `
        <div class="reward-info">
          <strong>${r.minutes_awarded >= 0 ? '+' : ''}${r.minutes_awarded} Minutes</strong>
          <span>${timeStr} • ${r.note || "Reward"}</span>
        </div>
        <div class="reward-status">
          ${r.synced_to_switch ? "🎮 Added to Switch" : "🏦 Banked"}
        </div>
      `;
      rewardsList.appendChild(item);
    });
  } catch (err) {
    console.error("Failed to load reward history", err);
  }
}

// Settings & Nintendo Integration Modal
function setupSettingsUI() {
  openSettingsBtn.addEventListener("click", async () => {
    await loadSettingsData();
    settingsModal.classList.remove("hidden");
  });

  closeSettingsBtn.addEventListener("click", () => {
    settingsModal.classList.add("hidden");
  });

  saveSettingsBtn.addEventListener("click", saveSettingsData);

  loginNintendoBtn.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/nintendo/login-url");
      const data = await res.json();
      nintendoLoginLink.href = data.login_url;
      callbackUrlInput.value = "";
      loginModal.classList.remove("hidden");
    } catch (err) {
      alert("Could not start Nintendo login: " + err);
    }
  });

  closeLoginModalBtn.addEventListener("click", () => {
    loginModal.classList.add("hidden");
  });

  submitLoginCallbackBtn.addEventListener("click", async () => {
    const url = callbackUrlInput.value.trim();
    if (!url) {
      alert("Please paste the copied URL.");
      return;
    }

    submitLoginCallbackBtn.disabled = true;
    submitLoginCallbackBtn.textContent = "Connecting...";

    try {
      const res = await fetch("/api/nintendo/complete-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ response_url: url }),
      });
      const data = await res.json();
      if (res.ok) {
        alert("Nintendo account connected successfully!");
        loginModal.classList.add("hidden");
        refreshStatus();
        await loadSettingsData();
      } else {
        alert("Connection failed: " + (data.detail || "Invalid response URL"));
      }
    } catch (err) {
      alert("Error: " + err);
    } finally {
      submitLoginCallbackBtn.disabled = false;
      submitLoginCallbackBtn.textContent = "Complete Connection";
    }
  });

  const resetAllowanceSettingsBtn = document.getElementById("resetAllowanceSettingsBtn");
  if (resetAllowanceSettingsBtn) {
    resetAllowanceSettingsBtn.addEventListener("click", async () => {
      await performResetTodayAllowance();
      settingsModal.classList.add("hidden");
    });
  }

  const resetBankSettingsBtn = document.getElementById("resetBankSettingsBtn");
  if (resetBankSettingsBtn) {
    resetBankSettingsBtn.addEventListener("click", async () => {
      await performResetBank();
      settingsModal.classList.add("hidden");
    });
  }
}

async function loadSettingsData() {
  const res = await fetch("/api/settings");
  const data = await res.json();

  document.getElementById("settingQuestionsPerReward").value = data.questions_per_reward;
  document.getElementById("settingMinutesPerReward").value = data.minutes_per_reward;
  document.getElementById("settingMaxDailyMins").value = data.max_daily_reward_minutes;
  document.getElementById("settingSpeedThreshold").value = (data.speed_threshold_ms / 1000).toFixed(1);
  if (settingRewardMode) settingRewardMode.value = data.reward_mode || "hybrid";
  const excludeTwosEl = document.getElementById("settingExcludeTwos");
  if (excludeTwosEl) excludeTwosEl.checked = !!data.exclude_twos;
  const excludeTensEl = document.getElementById("settingExcludeTens");
  if (excludeTensEl) excludeTensEl.checked = !!data.exclude_tens;
  const excludeElevensEl = document.getElementById("settingExcludeElevensSingleDigit") || document.getElementById("settingExcludeElevensTwoDigit");
  if (excludeElevensEl) excludeElevensEl.checked = !!(data.exclude_elevens_single_digit !== undefined ? data.exclude_elevens_single_digit : data.exclude_elevens_two_digit);

  // Active tables chips
  const tableToggles = document.getElementById("tableToggles");
  tableToggles.innerHTML = "";
  const activeSet = new Set(data.active_tables || []);

  for (let t = 2; t <= 12; t++) {
    const chip = document.createElement("div");
    chip.className = `table-chip ${activeSet.has(t) ? "selected" : ""}`;
    chip.textContent = `${t}s`;
    chip.dataset.table = t;
    chip.addEventListener("click", () => {
      chip.classList.toggle("selected");
    });
    tableToggles.appendChild(chip);
  }

  // Nintendo Status & Devices
  const statusRes = await fetch("/api/status");
  const statusData = await statusRes.json();

  if (statusData.nintendo_connected) {
    nintendoDetailText.innerHTML = `<strong>Connected!</strong> Found ${statusData.devices.length} Switch console(s).`;
    deviceSelect.innerHTML = "";
    statusData.devices.forEach(d => {
      const opt = document.createElement("option");
      opt.value = d.device_id;
      opt.textContent = `${d.name} (${d.today_time_remaining}m remaining today)`;
      if (d.device_id === statusData.selected_device_id) opt.selected = true;
      deviceSelect.appendChild(opt);
    });
    loginNintendoBtn.textContent = "Re-connect Nintendo Account";
  } else {
    const errMsg = statusData.nintendo_last_error ? `<br><small style="color:#ef4444">${escapeHtml(statusData.nintendo_last_error)}</small>` : "";
    nintendoDetailText.innerHTML = `Not connected. Sign in to link your Nintendo Switch.${errMsg}`;
    deviceSelect.innerHTML = '<option value="">(No devices connected)</option>';
    loginNintendoBtn.textContent = "Connect Nintendo Account";
  }
}

async function saveSettingsData() {
  const selectedTables = [];
  document.querySelectorAll(".table-chip.selected").forEach(c => {
    selectedTables.push(parseInt(c.dataset.table, 10));
  });

  const payload = {
    questions_per_reward: parseInt(document.getElementById("settingQuestionsPerReward").value, 10),
    minutes_per_reward: parseInt(document.getElementById("settingMinutesPerReward").value, 10),
    max_daily_reward_minutes: parseInt(document.getElementById("settingMaxDailyMins").value, 10),
    speed_threshold_ms: parseFloat(document.getElementById("settingSpeedThreshold").value) * 1000,
    active_tables: selectedTables.length > 0 ? selectedTables : Array.from({length: 11}, (_, i) => i + 2),
    selected_device_id: deviceSelect.value || null,
    reward_mode: settingRewardMode ? settingRewardMode.value : "hybrid",
    exclude_twos: document.getElementById("settingExcludeTwos") ? document.getElementById("settingExcludeTwos").checked : false,
    exclude_tens: document.getElementById("settingExcludeTens") ? document.getElementById("settingExcludeTens").checked : false,
    exclude_elevens_single_digit: (document.getElementById("settingExcludeElevensSingleDigit") || document.getElementById("settingExcludeElevensTwoDigit")) ? (document.getElementById("settingExcludeElevensSingleDigit") || document.getElementById("settingExcludeElevensTwoDigit")).checked : false,
    exclude_elevens_two_digit: (document.getElementById("settingExcludeElevensSingleDigit") || document.getElementById("settingExcludeElevensTwoDigit")) ? (document.getElementById("settingExcludeElevensSingleDigit") || document.getElementById("settingExcludeElevensTwoDigit")).checked : false,
  };

  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      alert("Settings saved!");
      settingsModal.classList.add("hidden");
      refreshStatus();
    } else {
      alert("Failed to save settings.");
    }
  } catch (err) {
    alert("Error saving settings: " + err);
  }
}
