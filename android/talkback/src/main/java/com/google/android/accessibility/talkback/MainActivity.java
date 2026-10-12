/*
 * Copyright (C) 2024 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy of
 * the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
 * WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
 * License for the specific language governing permissions and limitations under
 * the License.
 */

package com.google.android.accessibility.talkback;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.TextView;

/**
 * Main entry point for TalkBack application.
 * Provides basic information about TalkBack and access to settings.
 */
public class MainActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        // Set up the main title
        TextView titleView = findViewById(R.id.main_title);
        titleView.setText("FocalFlow");

        // Set up the description
        TextView descriptionView = findViewById(R.id.main_description);
        descriptionView.setText("Enable FocalFlow first, then start the computer program. FocalFlow turns off when that connection ends.");

        // Set up the enable button
        Button enableButton = findViewById(R.id.btn_enable_talkback);
        enableButton.setText("Enable / disable FocalFlow");
        enableButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                openAccessibilitySettings();
            }
        });

        // Set up the settings button
        Button settingsButton = findViewById(R.id.btn_settings);
        settingsButton.setText("FocalFlow Settings");
        settingsButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                openTalkBackSettings();
            }
        });

        // Set up the help text
        TextView helpText = findViewById(R.id.help_text);
        helpText.setText("To exit while waiting for the computer, open Accessibility settings and turn off FocalFlow.");
    }

    /**
     * Opens the Android accessibility settings where users can enable TalkBack.
     */
    private void openAccessibilitySettings() {
        Intent intent = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
        if (intent.resolveActivity(getPackageManager()) != null) {
            startActivity(intent);
        }
    }

    /**
     * Opens TalkBack preferences activity.
     */
    private void openTalkBackSettings() {
        try {
            Intent intent = new Intent(this, com.android.talkback.TalkBackPreferencesActivity.class);
            startActivity(intent);
        } catch (Exception e) {
            // Fallback to accessibility settings if TalkBackPreferencesActivity is not available
            openAccessibilitySettings();
        }
    }
} 