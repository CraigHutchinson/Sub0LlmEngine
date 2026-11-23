// The one translation unit that compiles Asio and Beast (BOOST_*_SEPARATE_COMPILATION, set on the net target): every other file
// that includes them only declares.
#include <boost/asio/impl/src.hpp>
#include <boost/beast/src.hpp>
