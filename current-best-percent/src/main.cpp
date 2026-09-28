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

    // Same text the game itself puts in the label: "12%", or "12.34%" when the
    // game's decimal percentage option is on.
    std::string formatCurrent(float percent, bool decimals) {
        if (decimals) {
            return fmt::format("{:.2f}%", percent);
        }
        return fmt::format("{}%", static_cast<int>(percent));
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

        auto text = fmt::format("{} / {}%", formatCurrent(percent, m_decimalPercentage), best);
        if (text != m_percentageLabel->getString()) {
            m_percentageLabel->setString(text.c_str());
        }
    }

    void updateProgressbar() {
        PlayLayer::updateProgressbar();
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
            auto percent = currentPercent(playLayer);
            playLayer->m_percentageLabel->setString(formatCurrent(percent, playLayer->m_decimalPercentage).c_str());
        }
        playLayer->updateProgressbar();
    });
}
