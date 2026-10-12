> Historical background, not the current setup or acceptance guide. See
> [README.md](README.md) and [protocol v1](docs/protocol-v1.md) for the
> maintained candidate. Sensitive FocalFlow history is now off by default;
> transport snapshots, freshness checks and local pause/resume have changed.
> Examples below have not been revalidated and are not device-test evidence.

# Core Architectural Modules

This document outlines the core architectural components of TalkBack, focusing on how it processes user interactions and system events to provide accessible feedback. The architecture is designed around a pipeline that transforms raw events into meaningful feedback for the user.

## 1. Event Processing and Dispatch

The journey of an event in TalkBack begins with its reception and initial handling. This is primarily managed by:

*   **`TalkBackService.java`**: As the heart of TalkBack, this service extends Android's `AccessibilityService`. Its key responsibilities in event processing include:
    *   **Receiving Accessibility Events**: Listening to all accessibility events dispatched by the Android system (e.g., focus changes, window state changes, view clicks).
    *   **Initial Event Handling**: Performing preliminary processing or filtering of events.
    *   **Dispatching to Pipeline**: Forwarding the events to the `Pipeline` for further processing.
    *   **Lifecycle Management**: Managing the lifecycle of TalkBack and its components.

*   **`eventprocessor/` module**: This module likely contains more specialized classes for handling different types of system accessibility events before they are passed into the main pipeline. It acts as an initial layer of event organization and preparation.

*   **`Pipeline.java`**: This class represents the central data flow architecture in TalkBack. For event processing, its roles are:
    *   **Unified Event Input**: Providing a standardized entry point for events (both system accessibility events and internally generated events) into the processing chain.
    *   **Sequencing**: Managing the order of processing steps for an event.

## 2. Event Interpretation

Once an event enters the `Pipeline`, it needs to be interpreted to understand its semantic meaning in the context of the user interface and ongoing interactions. This is the responsibility of:

*   **`interpreters/` module**: This directory houses various event interpreter classes. Each interpreter is likely specialized in understanding specific types of events or contexts.
    *   **Examples from `README.md`**: `Interpreters.java` manages instances of focus interpreters, scroll interpreters, state change interpreters, full-screen reading interpreters, and input method interpreters.
    *   **Function**: They transform raw accessibility events (e.g., "view focused," "text changed") into a more abstract `Interpretation`.

*   **`Interpretation.java`**: This class defines the data structure for the output of the interpretation phase. It encapsulates the semantic meaning of an event, such as what action occurred, on what UI element, and any relevant data (e.g., the text of a focused node). This standardized format allows subsequent components to work with a consistent understanding of the event.

*   **`Pipeline.java`**: Coordinates the flow of an event through the relevant `Interpreter` or chain of `Interpreters`.

## 3. Feedback Composition and Generation

After an event is interpreted, TalkBack determines the appropriate feedback to provide to the user. If speech is part of the feedback, it needs to be composed.

*   **`compositor/` module**: This module is central to generating the content of spoken feedback.
    *   **`rule/` (Speech Rule Engine)**: Contains rules that define how to describe different UI elements, states, and actions. For example, it might have rules to announce a button as "Button, [label], double-tap to activate."
    *   **`parsetree/` (Speech Parse Tree)**: Likely involved in constructing more complex spoken announcements by organizing pieces of information into a structured tree before linearization into speech.
    *   **`hint/` (Hint Processing)**: Manages usage hints that can be appended to announcements (e.g., "double-tap to activate").
    *   **Function**: The compositor takes the `Interpretation` and other contextual information, applies rules, and generates a structured representation of the feedback to be spoken.

*   **`Feedback.java`**: This class defines the data structures for all types of feedback TalkBack can produce, not just speech.
    *   **Types**: Includes `Speech`, `Sound`, `Vibration`, `Focus` actions, `Scroll` actions, etc.
    *   **Builder Pattern**: Provides a way to construct complex feedback objects that might involve multiple types of feedback (e.g., speak an announcement and play a sound).
    *   **Priority and Interruption**: Manages rules for feedback priority (e.g., an important notification might interrupt less important feedback) and how feedback can be queued or interrupted.

*   **`Pipeline.java`**: After interpretation, the `Pipeline` would pass the `Interpretation` to components responsible for deciding on the appropriate `Feedback` (which could involve the `compositor` if speech is needed).

## 4. Feedback Execution

The final stage is the execution of the composed feedback, delivering it to the user.

*   **`actor/` module**: This directory contains the "Feedback Actuators" or `Actors`. Each actor is responsible for a specific type of feedback.
    *   **`Actors.java`**: This class (mentioned in `README.md`) likely acts as a manager or registry for all individual actor instances. It receives a `Feedback` object and dispatches it to the appropriate actor(s).
    *   **Examples of Actor types (from `README.md` under `Actors.java`)**:
        *   **Speech Actor**: Interacts with the Text-To-Speech (TTS) engine to speak announcements.
        *   **Sound/Vibration Actor**: Plays earcons or triggers haptic feedback.
        *   **Focus Actor**: Performs focus manipulations (e.g., moving accessibility focus).
        *   **Navigation Actor**: Handles navigational actions.
        *   Other actors for text editing, scrolling, screen dimming, etc.

*   **`Pipeline.java`**: Ensures that after interpretation and feedback composition, the resulting `Feedback` object is sent to the `Actors` for execution. It also manages feedback-related concerns like latency and interruption mechanisms.

*   **`speech/` module**: While `compositor/` deals with *what* to say, the `speech/` module likely handles the *how* of saying it, managing the Text-To-Speech (TTS) engine, speech parameters (rate, pitch), and the queue of utterances.

This layered architecture, from event capture to feedback execution, allows TalkBack to process complex interactions and provide timely, relevant feedback to the user, making Android accessible. The `Pipeline` serves as the backbone, ensuring a smooth flow of data and control between these specialized modules.
