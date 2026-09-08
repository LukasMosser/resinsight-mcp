#include <expected>
#include <format>
#include <iostream>
#include <string>

int main() {
    std::expected<int, std::string> value = 42;
    std::cout << std::format("C++23 expected and format: {}\n", value.value());
}
