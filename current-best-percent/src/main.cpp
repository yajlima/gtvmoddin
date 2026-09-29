#include <Geode/Geode.hpp>
#include <Geode/modify/PlayLayer.hpp>

#include <algorithm>
#include <cmath>
#include <string>

using namespace geode::prelude;

namespace {
    bool modEnabled() {
        return Mod::get()->getSettingValue<bool>("enabled");
    }

    int decimalPlaces() {
        return static_cast<int>(std::clamp<int64_t>(Mod::get()->getSettingValue<int64_t>("decimals"), 0, 3));
    }

    // "7%" with 0 decimals, "7.412%" with 3. Truncates instead of rounding so it
    // never reads 100% before the level is actually finished.
    std::string formatPercent(float percent, int decimals) {
        if (decimals <= 0) {
            return fmt::format("{}%", static_cast<int>(percent));
        }
        auto scale = std::pow(10.0, decimals);
        auto truncated = std::floor(static_cast<double>(percent) * scale) / scale;
        return fmt::format("{:.{}f}%", truncated, decimals);
    }

    // Current run progress clamped to 0-100 (and 0 if the level has no length)
    float currentPercent(PlayLayer* playLayer) {
        auto percent = playLayer->getCurrentPercent();
        return std::isfinite(percent) ? std::clamp(percent, 0.f, 100.f) : 0.f;
    }
}

class $modify(BestPercentPlayLayer, PlayLayer) {
    struct Fields {
        // Highest whole percent reached in the current attempt while that attempt
        // counts toward the normal-mode best. Lets the best update the moment the
        // record is passed, before the game saves it on death / completion.
        int attemptBest = 0;
    };

    // A run only sets a normal-mode record outside practice mode, without a
    // start position and without ignore damage.
    bool countsTowardNormalBest() {
        return !m_isPracticeMode && !m_isTestMode && !m_isIgnoreDamageEnabled;
    }

    void refreshBestLabel() {
        if (!modEnabled() || !m_percentageLabel || !m_level || m_level->isPlatformer()) {
            return;
        }

        auto percent = currentPercent(this);
        auto best = m_level->m_normalPercent.value();

        if (this->countsTowardNormalBest()) {
            auto fields = m_fields.self();
            fields->attemptBest = std::max(fields->attemptBest, static_cast<int>(percent));
            best = std::max(best, fields->attemptBest);
        }
        best = std::clamp(best, 0, 100);

        auto text = fmt::format("{} / {}%", formatPercent(percent, decimalPlaces()), best);
        if (text != m_percentageLabel->getString()) {
            m_percentageLabel->setString(text.c_str());
        }
        // Show it even when the game's own Show Percentage option is off
        if (!m_percentageLabel->isVisible()) {
            m_percentageLabel->setVisible(true);
        }
    }

    void updateProgressbar() {
        PlayLayer::updateProgressbar();
        this->refreshBestLabel();
    }

    // Runs once per frame after the game's own per-frame work, so our text wins
    // even if the game writes the label somewhere updateProgressbar isn't hooked
    void postUpdate(float dt) {
        PlayLayer::postUpdate(dt);
        this->refreshBestLabel();
    }

    void resetLevel() {
        PlayLayer::resetLevel();
        // The game has saved any record from the previous attempt by now, so the
        // saved best takes over again.
        m_fields->attemptBest = 0;
        this->refreshBestLabel();
    }
};

$on_mod(Loaded) {
    listenForSettingChanges<bool>("enabled", [](bool enabled) {
        auto playLayer = PlayLayer::get();
        if (!playLayer || !playLayer->m_percentageLabel || !playLayer->m_level || playLayer->m_level->isPlatformer()) {
            return;
        }
        if (!enabled) {
            // Put the vanilla text back right away instead of waiting for the next update
            // (the game's own decimal option shows 2 places)
            auto percent = currentPercent(playLayer);
            auto vanilla = formatPercent(percent, playLayer->m_decimalPercentage ? 2 : 0);
            playLayer->m_percentageLabel->setString(vanilla.c_str());
        }
        playLayer->updateProgressbar();
    });
    listenForSettingChanges<int64_t>("decimals", [](int64_t) {
        if (auto playLayer = PlayLayer::get()) {
            playLayer->updateProgressbar();
        }
    });
}
