import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui

Item {
    id: root
    property var shell: null
    property var plugins: []
    property var counts: ({ enabled: 0, native: 0, attention: 0 })
    property string message: "Loading integrations…"
    property string query: ""
    property bool closingFromHost: false
    property bool opened: false
    readonly property var visiblePlugins: plugins.filter(function(plugin) {
        var needle = query.trim().toLowerCase()
        if (!needle) return true
        return (plugin.label + " " + plugin.id + " " + plugin.category + " " + plugin.description).toLowerCase().indexOf(needle) !== -1
    })

    function open(payloadJson) {
        closingFromHost = false
        opened = true
        refresh.running = true
        Qt.callLater(function() { search.forceActiveFocus() })
    }
    function close() { closingFromHost = true; opened = false; closingFromHost = false }
    function requestClose() {
        if (shell && typeof shell.hide === "function") shell.hide("io.github.oldjobobo.thpm")
        else opened = false
    }
    function refreshState() {
        try {
            var state = JSON.parse(stateOutput.text)
            plugins = state.plugins || []
            counts = state.counts || counts
            message = state.ok ? "" : (state.summary || "Unable to read THPM state")
        } catch (error) { message = "Unable to read THPM state" }
    }
    function setPlugin(id, enabled) {
        mutate.command = ["thpm", "--json", "plugin", enabled ? "enable" : "disable", id]
        mutate.running = true
    }

    Process {
        id: refresh
        command: ["thpm", "--json", "ui", "state"]
        stdout: StdioCollector { id: stateOutput; onStreamFinished: root.refreshState() }
    }
    Process {
        id: mutate
        stdout: StdioCollector { onStreamFinished: refresh.running = true }
    }

    PanelWindow {
        id: surface
        visible: root.opened
        color: "transparent"
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.namespace: "thpm-manager"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
        anchors { top: true; right: true; bottom: true; left: true }

        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, 0.32)
        }

        MouseArea {
            anchors.fill: parent
            onClicked: root.requestClose()
        }

        BorderSurface {
            id: card
            anchors.centerIn: parent
            width: Math.min(640, surface.width - Style.space(32))
            height: Math.min(700, surface.height - Style.space(48))
            radius: Style.cornerRadius
            color: Color.popups.background
            borderSpec: Border.surfaceSpec("popups", "border", Color.popups.border, Math.max(1, Style.normalBorderWidth))

            MouseArea {
                anchors.fill: parent
                onClicked: function(mouse) { mouse.accepted = true }
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Style.space(20)
                spacing: Style.space(14)

                RowLayout {
                    Layout.fillWidth: true

                    ColumnLayout {
                        spacing: Style.space(2)
                        Text {
                            text: "Theme hooks"
                            color: Color.foreground
                            font.family: Style.font.family
                            font.pixelSize: Style.font.title
                            font.bold: true
                        }
                        Text {
                            text: root.counts.enabled + " enabled  ·  " + root.counts.native + " handled by Omarchy"
                            color: Qt.darker(Color.foreground, 1.45)
                            font.family: Style.font.family
                            font.pixelSize: Style.font.caption
                        }
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        iconText: "󰑐"
                        tooltipText: "Refresh"
                        focusable: true
                        onClicked: refresh.running = true
                    }
                    Button {
                        iconText: "󰅖"
                        tooltipText: "Close"
                        focusable: true
                        onClicked: root.requestClose()
                    }
                }

                TextField {
                    id: search
                    Layout.fillWidth: true
                    placeholderText: "Search integrations"
                    text: root.query
                    onTextChanged: root.query = text
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: root.message !== "" || root.counts.attention > 0
                    spacing: Style.space(6)
                    Text {
                        text: root.message !== "" ? root.message : root.counts.attention + " integrations need attention"
                        color: root.message !== "" ? Color.urgent : Qt.darker(Color.foreground, 1.35)
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                    }
                    Item { Layout.fillWidth: true }
                }

                QQC.ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true

                    ListView {
                        id: pluginList
                        model: root.visiblePlugins
                        spacing: Style.space(6)
                        boundsBehavior: Flickable.StopAtBounds

                        delegate: Toggle {
                            required property var modelData
                            width: ListView.view.width
                            label: modelData.label
                            description: modelData.ownership === "native"
                                ? "Managed by Omarchy · " + modelData.description
                                : (!modelData.available ? "Not installed · " : "") + modelData.description
                            checked: modelData.enabled
                            enabled: modelData.ownership !== "native" && modelData.available && !mutate.running
                            opacity: enabled ? 1.0 : 0.58
                            onClicked: if (enabled) root.setPlugin(modelData.id, !checked)
                        }
                    }
                }

                Text {
                    Layout.alignment: Qt.AlignHCenter
                    visible: root.visiblePlugins.length === 0
                    text: "No matching integrations"
                    color: Qt.darker(Color.foreground, 1.45)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                }

                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Esc to close"
                    color: Qt.darker(Color.foreground, 1.6)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                }
            }
        }
        Shortcut { sequence: "Escape"; onActivated: root.requestClose() }
    }
}
