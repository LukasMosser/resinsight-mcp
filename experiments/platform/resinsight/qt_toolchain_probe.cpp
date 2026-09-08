#include <QtCore/QCoreApplication>
#include <QtCore/QString>
#include <QtCore/QTimer>

#include <expected>
#include <format>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
    QCoreApplication application(argc, argv);
    QTimer::singleShot(0, &application, [&application] {
        const std::string message = std::format("Qt {} C++23 value {}", qVersion(), 42);
        if (QString::fromStdString(message).toStdString() != message) {
            application.exit(1);
            return;
        }
        std::expected<int, std::string> missing = std::unexpected("expected probe error");
        try {
            missing.value();
            application.exit(2);
        } catch (const std::bad_expected_access<std::string>& error) {
            if (error.error() != "expected probe error") {
                application.exit(3);
                return;
            }
            std::cout << message << "\nQt event loop, string exchange, and exception passed\n";
            application.exit(0);
        }
    });
    return application.exec();
}
